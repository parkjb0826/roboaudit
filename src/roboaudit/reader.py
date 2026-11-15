"""RoboAudit 읽기 계층.

LeRobot v2.1 / v3.0 데이터셋을 공통 형태로 읽는다.
- 에피소드 메타 (길이, 파일 경로, 지시문, v3.0 인덱스 구간·영상 구간)
- 에피소드 데이터 (state/action/timestamp 배열)
- 에피소드 영상 프레임 (v3.0 공유 파일은 시간 구간으로 슬라이스)
- 성공/실패 라벨 존재 여부

원본은 읽기 전용으로만 접근한다.

4단계 실데이터 대응:
- 영상 키가 observation.images.top 이 아닌 데이터셋이 대부분이라 키를 해석한다.
- 실데이터 영상은 AV1 코덱이 많은데 이 환경의 OpenCV는 AV1 디코딩이 안 돼,
  실패 시 시스템 ffmpeg(libdav1d)로 폴백 디코딩한다.

보강(5단계) 변경:
- 멀티 카메라: 선언된 모든 영상 키를 에피소드별 cameras dict로 제공한다.
- 디코딩 통계: 카메라별로 디코딩 성공/실패/파일 없음 에피소드와 사용 백엔드를
  기록한다 (검사 상태 분리의 근거 — 실패가 '정상'으로 집계되지 않게).
- 표본 모드: sample_frames를 주면 에피소드당 최대 그 수만큼 균등 표본 디코딩.
  표본 전 전체 프레임 수(full count)는 따로 기록해 V3 길이 검사에 쓴다.
"""
import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

VIDEO_KEY = "observation.images.top"


def declared_video_keys(info: dict):
    """info.features에 선언된 영상(dtype=video) 키 전부, 선언 순서대로."""
    feats = info.get("features", {})
    return [k for k, v in feats.items()
            if isinstance(v, dict) and v.get("dtype") == "video"]


def resolve_video_key(root: Path, info: dict) -> str:
    """데이터셋이 실제로 쓰는 대표 영상 키를 정한다 (4단계 실데이터 대응).

    규칙: ① observation.images.top 이 선언돼 있으면 그것 (기존 동작과 동일)
          ② 아니면 디스크에 실제 폴더가 있는 첫 번째 영상 피처 (부분 다운로드 대응)
          ③ 그것도 없으면 선언된 첫 번째 영상 피처
    보강 이후에도 대표 키는 S1의 기존 파일 존재 검사가 쓰고, 나머지 카메라는
    cameras dict로 따로 감사한다.
    """
    vids = declared_video_keys(info)
    if not vids:
        return VIDEO_KEY
    if VIDEO_KEY in vids:
        return VIDEO_KEY
    vroot = root / "videos"
    for k in vids:
        if (vroot / k).exists() or (vroot / "chunk-000" / k).exists():
            return k
    return vids[0]


def load_info(root: Path) -> dict:
    return json.loads((root / "meta" / "info.json").read_text())


def version_of(info: dict) -> str:
    return info.get("codebase_version", "unknown")


def _looks_like_label(key: str) -> bool:
    k = key.lower()
    return "success" in k or "failure" in k or "succeed" in k


def episodes_meta(root: Path, info: dict):
    """에피소드 메타 공통 dict 리스트.

    항목: episode_index, length, tasks(list[str]), data_path, video_path(대표 키),
          from_index, to_index (v3.0만), video_from_ts, video_to_ts (v3.0만, 대표 키),
          cameras: {영상 키: {"path", "from_ts", "to_ts"}} (전 카메라)
    """
    ver = version_of(info)
    vkey = resolve_video_key(root, info)
    vids = declared_video_keys(info)
    eps = []
    if ver == "v2.1":
        chunks_size = info.get("chunks_size", 1000)
        for line in (root / "meta" / "episodes.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            ep = int(e["episode_index"])
            chunk = ep // chunks_size
            cameras = {k: {"path": root / "videos" / f"chunk-{chunk:03d}" / k
                           / f"episode_{ep:06d}.mp4",
                           "from_ts": None, "to_ts": None}
                       for k in vids}
            eps.append({
                "episode_index": ep,
                "length": int(e["length"]),
                "tasks": list(e.get("tasks", [])),
                "meta_keys": sorted(e.keys()),
                "data_path": root / "data" / f"chunk-{chunk:03d}" / f"episode_{ep:06d}.parquet",
                "video_path": cameras[vkey]["path"] if vkey in cameras else None,
                "cameras": cameras,
                "from_index": None, "to_index": None,
                "video_from_ts": None, "video_to_ts": None,
            })
    elif ver == "v3.0":
        meta_files = sorted((root / "meta" / "episodes").rglob("*.parquet"))
        rows = []
        for mf in meta_files:
            rows.extend(pq.read_table(mf).to_pylist())
        for e in sorted(rows, key=lambda r: r["episode_index"]):
            cameras = {}
            for k in vids:
                ci, fi = f"videos/{k}/chunk_index", f"videos/{k}/file_index"
                if ci in e and e[ci] is not None:
                    cameras[k] = {
                        "path": root / "videos" / k / f"chunk-{int(e[ci]):03d}"
                                / f"file-{int(e[fi]):03d}.mp4",
                        "from_ts": float(e[f"videos/{k}/from_timestamp"]),
                        "to_ts": float(e[f"videos/{k}/to_timestamp"]),
                    }
                else:
                    cameras[k] = {"path": None, "from_ts": None, "to_ts": None}
            prim = cameras.get(vkey, {"path": None, "from_ts": None, "to_ts": None})
            eps.append({
                "episode_index": int(e["episode_index"]),
                "length": int(e["length"]),
                "tasks": list(e.get("tasks", []) or []),
                "meta_keys": sorted(e.keys()),
                "data_path": root / "data" / f"chunk-{int(e['data/chunk_index']):03d}" / f"file-{int(e['data/file_index']):03d}.parquet",
                "video_path": prim["path"],
                "cameras": cameras,
                "from_index": int(e["dataset_from_index"]),
                "to_index": int(e["dataset_to_index"]),
                "video_from_ts": prim["from_ts"],
                "video_to_ts": prim["to_ts"],
            })
    else:
        raise ValueError(f"unsupported codebase_version: {ver}")
    return eps


def _table_to_arrays(tbl):
    cols = tbl.to_pydict()
    n = tbl.num_rows
    state = np.array(cols["observation.state"], dtype=np.float32).reshape(n, -1)
    action = np.array(cols["action"], dtype=np.float32).reshape(n, -1)
    return {
        "episode_index": np.array(cols["episode_index"], dtype=np.int64),
        "frame_index": np.array(cols["frame_index"], dtype=np.int64),
        "timestamp": np.array(cols["timestamp"], dtype=np.float64),
        "task_index": np.array(cols["task_index"], dtype=np.int64) if "task_index" in cols else None,
        "state": state,
        "action": action,
        "columns": list(cols.keys()),
    }


class DatasetReader:
    """버전 공통 에피소드 데이터·영상 접근. 파일 단위로 캐시한다."""

    def __init__(self, root: Path, sample_frames=None):
        self.root = root
        self.info = load_info(root)
        self.version = version_of(self.info)
        self.video_key = resolve_video_key(root, self.info)
        self.video_keys = declared_video_keys(self.info)
        self.episodes = episodes_meta(root, self.info)
        self.sample_frames = sample_frames
        self._cache = {}
        # 카메라별 디코딩 통계 (검사 상태·범위의 근거)
        self.decode_stats = {}
        self._frame_counts = {}  # (episode_index, video_key) -> 표본 전 프레임 수

    # ----- 데이터 -----
    def episode_data(self, ep_meta) -> dict:
        path = ep_meta["data_path"]
        if path not in self._cache:
            self._cache[path] = _table_to_arrays(pq.read_table(path))
        full = self._cache[path]
        mask = full["episode_index"] == ep_meta["episode_index"]
        out = {k: (v[mask] if isinstance(v, np.ndarray) else v)
               for k, v in full.items()}
        return out

    def data_columns(self, ep_meta):
        path = ep_meta["data_path"]
        if path not in self._cache:
            self._cache[path] = _table_to_arrays(pq.read_table(path))
        return self._cache[path]["columns"]

    def total_data_rows(self) -> int:
        total = 0
        seen = set()
        for e in self.episodes:
            if e["data_path"] not in seen:
                seen.add(e["data_path"])
                total += pq.read_metadata(e["data_path"]).num_rows
        return total

    def data_availability(self):
        """(읽힌 에피소드 집합, 못 읽은 에피소드 집합). 검사 상태 산정용."""
        ok, bad = set(), set()
        for e in self.episodes:
            try:
                self.episode_data(e)
                ok.add(e["episode_index"])
            except Exception:
                bad.add(e["episode_index"])
        return ok, bad

    # ----- 영상 -----
    @staticmethod
    def _video_size(path: Path):
        cap = cv2.VideoCapture(str(path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return w, h, n

    def _decode_ffmpeg(self, path: Path, start=None, dur=None, step=1):
        """ffmpeg(rawvideo 파이프)로 디코딩. AV1 등 OpenCV가 못 읽는 코덱용.
        step>1이면 select 필터로 균등 표본 디코딩 (표본 모드)."""
        if shutil.which("ffmpeg") is None or not path.exists():
            return None
        w, h, _ = self._video_size(path)
        if w <= 0 or h <= 0:
            return None
        cmd = ["ffmpeg", "-v", "error"]
        if start is not None:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(path)]
        if dur is not None:
            cmd += ["-t", f"{dur:.3f}"]
        if step and step > 1:
            cmd += ["-vf", f"select='not(mod(n\\,{step}))'"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-an", "-"]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=1800).stdout
        except Exception:
            return None
        unit = w * h * 3
        n = len(out) // unit
        if n == 0:
            return None
        arr = np.frombuffer(out[:n * unit], dtype=np.uint8).reshape(n, h, w, 3)
        return [arr[i] for i in range(n)]

    def _decode_video(self, path: Path):
        """파일 전체 디코딩. (프레임 리스트, 백엔드) 반환, 실패 시 (None, None).
        OpenCV 우선, 0프레임이면 ffmpeg 폴백."""
        if not path.exists():
            return None, None
        cap = cv2.VideoCapture(str(path))
        got = []
        while True:
            ret, fr = cap.read()
            if not ret:
                break
            got.append(fr)
        cap.release()
        if got:
            return got, "opencv"
        frames = self._decode_ffmpeg(path)
        if frames:
            return frames, "ffmpeg"
        return None, None

    def _sample_step(self, expected_frames: int) -> int:
        if not self.sample_frames or expected_frames <= self.sample_frames:
            return 1
        return max(1, math.ceil(expected_frames / self.sample_frames))

    def frame_count(self, episode_index: int, video_key: str):
        """표본 전(디코딩된) 프레임 수. 아직 디코딩 안 했으면 None."""
        return self._frame_counts.get((episode_index, video_key))

    def episode_frames(self, ep_meta, video_key=None):
        """에피소드 영상 프레임 리스트 (BGR). 없거나 못 읽으면 None.

        video_key를 주면 그 카메라, 없으면 대표 카메라. 표본 모드에서는
        균등 표본만 반환하고 전체 프레임 수는 frame_count()에 남긴다.
        디코딩 결과(성공/실패/파일 없음/백엔드)는 decode_stats에 기록된다.
        """
        key = video_key or self.video_key
        ep = ep_meta["episode_index"]
        stats = self.decode_stats.setdefault(key, {
            "episodes_ok": set(), "episodes_failed": set(),
            "episodes_missing": set(), "frames_full": 0, "frames_sampled": 0,
            "backends": set()})
        cam = ep_meta.get("cameras", {}).get(key)
        path = cam["path"] if cam else ep_meta.get("video_path")
        if path is None or not path.exists():
            stats["episodes_missing"].add(ep)
            return None
        from_ts = cam["from_ts"] if cam else ep_meta.get("video_from_ts")
        step = self._sample_step(ep_meta["length"])
        frames, backend, full = None, None, None
        if from_ts is None:
            frames, backend = self._decode_video(path)
            if frames is not None:
                full = len(frames)
                if step > 1:
                    frames = frames[::step]
        else:
            # v3.0: 공유 파일에서 이 에피소드 구간만 잘라 낸다.
            to_ts = cam["to_ts"] if cam else ep_meta.get("video_to_ts")
            _, _, n_frames = self._video_size(path)
            if 0 < n_frames <= 5000:
                all_frames, backend = self._decode_video(path)
                if all_frames is not None:
                    fps = float(self.info.get("fps", 30))
                    start = int(round(from_ts * fps))
                    end = int(round(to_ts * fps))
                    seg = all_frames[start:end]
                    full = len(seg)
                    frames = seg[::step] if step > 1 else seg
            else:
                frames = self._decode_ffmpeg(path, start=from_ts,
                                              dur=to_ts - from_ts, step=step)
                if frames is not None:
                    backend = "ffmpeg"
                    fps = float(self.info.get("fps", 30))
                    full = int(round((to_ts - from_ts) * fps)) if step > 1 \
                        else len(frames)
        if not frames:
            stats["episodes_failed"].add(ep)
            return None
        stats["episodes_ok"].add(ep)
        stats["backends"].add(backend)
        stats["frames_full"] += int(full or len(frames))
        stats["frames_sampled"] += len(frames)
        self._frame_counts[(ep, key)] = int(full or len(frames))
        return frames

    def decode_summary(self):
        """카메라별 디코딩 통계 (JSON 직렬화 가능한 형태)."""
        out = {}
        for key, s in self.decode_stats.items():
            out[key] = {
                "episodes_decoded": len(s["episodes_ok"]),
                "episodes_failed": sorted(s["episodes_failed"]),
                "episodes_missing_file": sorted(s["episodes_missing"]),
                "frames_decoded_full": s["frames_full"],
                "frames_used_sampled": s["frames_sampled"],
                "backends_used": sorted(s["backends"]),
            }
        return out

    # ----- 라벨 -----
    def has_success_labels(self) -> bool:
        for e in self.episodes:
            if any(_looks_like_label(k) for k in e.get("meta_keys", [])):
                return True
        feats = self.info.get("features", {})
        return any(_looks_like_label(k) for k in feats.keys())
