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

0.3.1 변경:
- 공유 파일(>5,000프레임) 구간 디코딩을 프레임 단위 정확 슬라이스로 교체.
  0.3.0은 ffmpeg -ss/-t에 밀리초로 반올림한 길이를 넘겨, 구간 경계 프레임이
  이웃 에피소드에서 딸려 오거나(26장) 내용이 한 프레임 밀리는(25장이지만
  엉뚱한 구간) 오류가 있었다 (xarm_lift_medium에서 실증, report_cards_02
  SUMMARY.md 검증 노트). 새 방식은 시작 프레임보다 반 프레임 앞당겨 seek한
  뒤 -frames:v N으로 정확히 N장만 받는다 — 전수 디코딩 슬라이스와 픽셀
  단위로 일치함을 xarm 첫/중간/끝 에피소드에서 확인했다.
"""
import json
import math
import re
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
                "recorded_stats": {},
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
            # 에피소드 단위 기록 통계 (S4 비교용): stats/<피처>/<항목> 열이
            # 있으면 그 값을 그대로 보관한다.
            rec_stats = {}
            for feat in ("observation.state", "action"):
                st = {}
                for stat in ("mean", "std", "count"):
                    k = f"stats/{feat}/{stat}"
                    if k in e and e[k] is not None:
                        st[stat] = list(e[k])
                if st:
                    rec_stats[feat] = st
            eps.append({
                "episode_index": int(e["episode_index"]),
                "length": int(e["length"]),
                "tasks": list(e.get("tasks", []) or []),
                "meta_keys": sorted(e.keys()),
                "recorded_stats": rec_stats,
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

    def __init__(self, root: Path, sample_frames=None, max_episodes=None):
        self.root = root
        self.info = load_info(root)
        self.version = version_of(self.info)
        self.video_key = resolve_video_key(root, self.info)
        self.video_keys = declared_video_keys(self.info)
        self.episodes = episodes_meta(root, self.info)
        self.sample_frames = sample_frames
        # 에피소드 표본 감사 (0.3.2, --max-episodes): 인덱스 순 첫 N개만
        # 감사한다. 선언 총량과 대조하는 검사는 이 플래그를 보고 건너뛴다.
        self.max_episodes = max_episodes
        self.episode_sampled = False
        if max_episodes is not None:
            ordered = sorted(self.episodes,
                             key=lambda e: e["episode_index"])
            if len(ordered) > max_episodes:
                self.episodes = ordered[:max_episodes]
                self.episode_sampled = True
        self._cache = {}
        self._recorded_stats = ...
        self._dataset_card = ...
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

    def _decode_ffmpeg(self, path: Path):
        """ffmpeg(rawvideo 파이프)로 파일 전체를 디코딩한다. AV1 등 OpenCV가
        못 읽는 코덱용. 구간 디코딩은 _decode_ffmpeg_segment를 쓴다."""
        if shutil.which("ffmpeg") is None or not path.exists():
            return None
        w, h, _ = self._video_size(path)
        if w <= 0 or h <= 0:
            return None
        cmd = ["ffmpeg", "-v", "error", "-i", str(path),
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-an", "-"]
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

    def _decode_ffmpeg_segment(self, path: Path, start_frame: int,
                               n_frames: int, fps: float):
        """공유 파일에서 [start_frame, start_frame + n_frames) 구간을 프레임
        단위로 정확히 디코딩한다 (0.3.1).

        방법: 시작 프레임의 반 프레임 앞((start_frame - 0.5)/fps)으로 seek한
        뒤 -frames:v n_frames 로 정확히 n_frames장만 받는다. ffmpeg의 입력
        seek는 목표 시각 이후 첫 프레임부터 출력하므로, 반 프레임 앞당긴
        지점을 넘기면 출력은 정확히 start_frame에서 시작한다 (목표 프레임의
        pts는 seek 지점보다 뒤, 직전 프레임의 pts는 앞이라 경계가 반 프레임
        여유 안에서 확정된다). 파일이 구간보다 짧으면 있는 만큼만 돌아오고,
        그 부족분은 V3가 그대로 본다.
        """
        if shutil.which("ffmpeg") is None or not path.exists():
            return None
        if n_frames <= 0 or fps <= 0:
            return None
        w, h, _ = self._video_size(path)
        if w <= 0 or h <= 0:
            return None
        seek = max(0.0, (start_frame - 0.5) / fps) if start_frame > 0 else 0.0
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{seek:.6f}", "-i", str(path),
               "-frames:v", str(int(n_frames)),
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-an", "-"]
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
                # 프레임 단위 정확 슬라이스 (0.3.1): 메타 타임스탬프 구간을
                # 프레임 인덱스로 환산해 정확히 그만큼만 디코딩한다. 표본
                # 모드의 균등 표본은 작은 파일 경로와 동일하게 디코딩 후
                # [::step]으로 맞추고, full은 실제 디코딩된 구간 길이다.
                fps = float(self.info.get("fps", 30))
                start_frame = int(round(from_ts * fps))
                n_span = int(round((to_ts - from_ts) * fps))
                frames = self._decode_ffmpeg_segment(path, start_frame,
                                                      n_span, fps)
                if frames is not None:
                    backend = "ffmpeg"
                    full = len(frames)
                    if step > 1:
                        frames = frames[::step]
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

    # ----- 기록 통계·카드 (0.3.2, S4·S5용) -----
    def recorded_stats(self):
        """메타에 기록된 통계. 없으면 None.

        반환: {"dataset": stats.json 내용 또는 None,
               "per_episode": {episode_index: {피처: {mean/std/count}}} 또는 None,
               "source_dataset": 출처 문자열, "source_per_episode": 출처 문자열}
        에피소드 단위 기록은 v2.1의 episodes_stats.jsonl, v3.0의 에피소드
        메타 stats 열에서 온다.
        """
        if self._recorded_stats is not ...:
            return self._recorded_stats
        dataset, dataset_src = None, None
        p = self.root / "meta" / "stats.json"
        if p.exists():
            try:
                dataset = json.loads(p.read_text())
                dataset_src = "meta/stats.json"
            except Exception:
                dataset = None
        per_ep, per_ep_src = None, None
        if self.version == "v2.1":
            p = self.root / "meta" / "episodes_stats.jsonl"
            if p.exists():
                per_ep = {}
                try:
                    for line in p.read_text().splitlines():
                        if line.strip():
                            row = json.loads(line)
                            per_ep[int(row["episode_index"])] = \
                                row.get("stats", {})
                    per_ep_src = "meta/episodes_stats.jsonl"
                except Exception:
                    per_ep = None
        elif self.version == "v3.0":
            collected = {e["episode_index"]: e["recorded_stats"]
                         for e in self.episodes if e.get("recorded_stats")}
            if collected:
                per_ep = collected
                per_ep_src = "meta/episodes parquet stats columns"
        if dataset is None and per_ep is None:
            self._recorded_stats = None
        else:
            self._recorded_stats = {
                "dataset": dataset, "per_episode": per_ep,
                "source_dataset": dataset_src,
                "source_per_episode": per_ep_src}
        return self._recorded_stats

    def dataset_card(self):
        """데이터셋 카드(README.md)의 YAML 프론트매터 license 값.

        카드 파일이 없으면 None (부분 복사본일 수 있어 판단 보류).
        있으면 {"path": "README.md", "licenses": [값, ...]}.
        license가 리스트 형태면 항목을 전부 모은다.
        """
        if self._dataset_card is not ...:
            return self._dataset_card
        p = self.root / "README.md"
        if not p.exists():
            self._dataset_card = None
            return None
        text = p.read_text(encoding="utf-8", errors="replace")
        licenses = []
        if text.startswith("---"):
            end = text.find("\n---", 3)
            fm = text[3:end] if end != -1 else text[3:]
            lines = fm.splitlines()
            for i, line in enumerate(lines):
                m = re.match(r"^license\s*:\s*(.*)$", line.strip())
                if not m:
                    continue
                val = m.group(1).strip().strip("'\"")
                if val:
                    licenses.append(val)
                else:
                    for nxt in lines[i + 1:]:
                        mm = re.match(r"^-\s*(.+)$", nxt.strip())
                        if mm:
                            licenses.append(mm.group(1).strip().strip("'\""))
                        elif nxt.strip():
                            break
                break
        self._dataset_card = {"path": "README.md", "licenses": licenses}
        return self._dataset_card
