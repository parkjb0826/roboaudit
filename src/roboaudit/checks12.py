"""RoboAudit 검사 12종 (설계서 v1, 4절).

구조 S1 메타·파일 무결성(치명) / S2 차원·스키마·값 유효성(치명) / S3 시간축(경고)
영상 V1 검은·정지 화면(치명) / V2 흔들림·흐림(경고) / V3 에피소드 길이 이상(경고)
행동 A1 범위 이탈(치명) / A2 급격한 점프(경고) / A3 무동작 차원(경고) / A4 중복 에피소드(참고)
지시문 L1 누락·전부 동일(경고) / L2 성공·실패 표시 없음(참고)

전부 규칙+임계값. finding마다 근거 수치(evidence)를 남긴다.
기존 4종과의 대응: integrity→S1, boundary→S1, timestamp→S3, nan→S2(값 유효성).

보강(5단계) 변경:
- 영상 검사(V1·V2·V3)는 선언된 모든 카메라를 감사한다 (기존: 대표 1개).
  finding evidence에 camera를 넣고, 상대 판정(V2)은 카메라별로 계산한다.
- S1: 대표 카메라 외 카메라가 전 에피소드에서 파일이 없으면 데이터셋 단위
  1건으로, 일부만 없으면 에피소드 단위로 보고한다.
- Ctx가 표본 모드(sample_frames)와 카메라별 영상 통계를 지원한다.

0.3.0 변경 (전부 증거 전용 — 검출·점수·처분 규칙은 바꾸지 않는다):
- A2 finding에 증거를 덧붙인다: 타임스탬프가 정보성일 때만 계산하는 간격
  비율 분류와, 지배 차원에서의 observation.state 추종 라벨. 타임스탬프
  격자 진단은 diagnostics.py가 맡고 Ctx.timestamp_grid()로 공유한다.
"""
from pathlib import Path

import cv2
import numpy as np

from .reader import DatasetReader

RULES_VERSION = "rules-2026-11-17.1"

SEVERITY = {
    "S1": "critical", "S2": "critical", "S3": "warning",
    "V1": "critical", "V2": "warning", "V3": "warning",
    "A1": "critical", "A2": "warning", "A3": "warning", "A4": "info",
    "L1": "warning", "L2": "info",
}
CHECK_NAMES = {
    "S1": "메타·파일 무결성", "S2": "차원·스키마 정합성", "S3": "시간축",
    "V1": "검은·정지 화면", "V2": "흔들림·흐림", "V3": "에피소드 길이 이상",
    "A1": "범위 이탈", "A2": "급격한 점프", "A3": "무동작 차원",
    "A4": "중복 에피소드", "L1": "지시문 누락·전부 동일", "L2": "성공·실패 표시 없음",
}

# ----- 임계값 (전부 여기로 모음) -----
TH = {
    "black_brightness": 12.0,        # V1: 에피소드 평균 밝기 미만이면 검은 화면
    "static_diff": 0.5,              # V1: 연속 프레임 평균절대차 미만이면 동일 프레임으로 간주
    "static_ratio": 0.9,             # V1: 동일 프레임 비율 이상이면 정지 화면
    "blur_ratio": 0.3,               # V2: 에피소드 라플라시안 분산 중앙값 < 비율×데이터셋 중앙값
    "shake_ratio": 1.6,              # V2: 에피소드 프레임간 차이 중앙값 > 비율×데이터셋 중앙값 (4단계: max→중앙값 기준으로 교체)
    "shake_median_abs": 0.5,         # V2: 에피소드 중앙 차이 절대 하한 (노이즈성 미동 구간 오탐 방지)
    "shake_single_abs": 40.0,        # V2: 단일 프레임쌍 차이가 이 값(그레이 레벨)을 넘으면 그 자체로 흔들림/글리치
    "gap_factor": 1.5,               # S3: 간격 > factor/fps 이면 끊김
    "fps_tol": 0.2,                  # S3: |중앙간격 - 1/fps| > tol/fps 이면 fps 불일치
    "range_frac": 0.10,              # A1: 대역 밖 값 비율 초과 시
    "range_qlo": 0.001,              # A1: LOO 대역 하위 분위수 (4단계에서 Tukey 울타리 대체)
    "range_qhi": 0.999,              # A1: LOO 대역 상위 분위수
    "range_band_margin": 0.5,        # A1: LOO 대역을 양쪽으로 IQR×이 값만큼 확장 (경계 에피소드 오탐 방지)
    "jump_factor": 5.0,              # A2: 최대 스텝 > factor×중앙 스텝
    "jump_abs": 1.0,                 # A2: 최대 스텝 절대 하한 (L2 norm)
    "jump_dataset_factor": 3.0,      # A2: 하한 = max(jump_abs, factor×데이터셋 스텝 q99) (4단계 추가)
    "dead_std": 1e-6,                # A3: 차원 표준편차 미만이면 무동작
    "len_ratio": 2.0,                # V3: 길이가 중앙값의 ratio배 이상/이하이면 이상
    # --- 0.3.0 증거 전용 (점수·처분에 영향 없음) ---
    "interval_drop_ratio": 1.5,      # A2 증거: 간격 비율 >= 이 값이면 dropped-frame-looking
    "interval_normal_lo": 0.8,       # A2 증거: [lo, hi) 구간이면 normal-interval
    "interval_normal_hi": 1.25,      # A2 증거: 그 외 구간은 ambiguous
    "state_follow_frac": 0.5,        # A2 증거: state 동시/추종 판정 비율 (FOLLOWUP 방법)
}


def _f(check, episode_index, detail, evidence=None):
    return {"check": check, "severity": SEVERITY[check],
            "episode_index": episode_index, "detail": detail,
            "evidence": evidence or {}}


class Ctx:
    """검사 실행 컨텍스트: 리더 + 영상 통계 캐시 (카메라별)."""

    def __init__(self, root: Path, sample_frames=None):
        self.root = root
        self.reader = DatasetReader(root, sample_frames=sample_frames)
        self._vstats = {}
        self._ts_grid = None

    def timestamp_grid(self):
        """타임스탬프 격자 진단 (diagnostics.py). 감사당 1회만 계산해 캐시한다.
        검사 12종이 아니며 점수·처분에 쓰이지 않는다 — A2 증거 게이트와
        result.json의 diagnostics 항목이 공유한다."""
        if self._ts_grid is None:
            from .diagnostics import timestamp_grid_diagnostic
            self._ts_grid = timestamp_grid_diagnostic(self.reader)
        return self._ts_grid

    def video_stats(self, ep_meta, video_key=None):
        """에피소드 영상 통계. 영상 없으면 None.

        n_frames는 표본 전 전체 프레임 수(리더 기록), 통계 자체는 표본
        모드에서 표본 프레임으로 계산한다 (n_sampled에 표본 수 기록).
        """
        key = video_key or self.reader.video_key
        ck = (ep_meta["episode_index"], key)
        if ck in self._vstats:
            return self._vstats[ck]
        frames = self.reader.episode_frames(ep_meta, key)
        if not frames:
            self._vstats[ck] = None
            return None
        grays = [cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY) for fr in frames]
        brightness = float(np.mean([g.mean() for g in grays]))
        pair_diffs = [float(np.mean(np.abs(grays[i + 1].astype(np.float32)
                                           - grays[i].astype(np.float32))))
                      for i in range(len(grays) - 1)]
        lap_vars = [float(cv2.Laplacian(g, cv2.CV_64F).var()) for g in grays]
        full = self.reader.frame_count(ep_meta["episode_index"], key)
        # 표본 간격: pair_diffs는 표본 모드에서 step프레임 떨어진 쌍의 차이라
        # V2가 프레임당으로 정규화할 수 있게 간격을 함께 기록한다.
        step = max(1, round(full / len(frames))) if full else 1
        st = {"n_frames": full if full is not None else len(frames),
              "n_sampled": len(frames), "camera": key, "sample_step": step,
              "brightness": brightness,
              "pair_diffs": pair_diffs,
              "lap_median": float(np.median(lap_vars)) if lap_vars else 0.0}
        self._vstats[ck] = st
        return st


# ---------------- 구조 ----------------

def check_s1(ctx: Ctx):
    """메타·파일 무결성 + 경계(길이·인덱스 구간) — 기존 integrity/boundary 통합."""
    findings = []
    reader = ctx.reader
    info = reader.info
    eps = reader.episodes
    if len(eps) != int(info.get("total_episodes", -1)):
        findings.append(_f("S1", None,
                           f"episode count {len(eps)} != total_episodes {info.get('total_episodes')}",
                           {"meta_episodes": len(eps),
                            "total_episodes": info.get("total_episodes")}))
    sum_len = sum(e["length"] for e in eps)
    if int(info.get("total_frames", sum_len)) != sum_len:
        findings.append(_f("S1", None,
                           f"total_frames {info.get('total_frames')} != sum of episode lengths {sum_len}",
                           {"total_frames": info.get("total_frames"), "sum_lengths": sum_len}))
    for e in eps:
        ep = e["episode_index"]
        if not e["data_path"].exists():
            findings.append(_f("S1", ep, f"missing data file: {e['data_path'].relative_to(ctx.root)}"))
        if not e["video_path"].exists():
            findings.append(_f("S1", ep, f"missing video file: {e['video_path'].relative_to(ctx.root)}"))
        if e["data_path"].exists():
            try:
                d = reader.episode_data(e)
                actual = len(d["timestamp"])
            except Exception as exc:
                findings.append(_f("S1", ep, f"data file unreadable: {exc}"))
                continue
            if actual != e["length"]:
                findings.append(_f("S1", ep,
                                   f"meta length {e['length']} != actual rows {actual}",
                                   {"meta_length": e["length"], "actual_rows": actual}))
            if e["from_index"] is not None:
                span = e["to_index"] - e["from_index"]
                if span != e["length"]:
                    findings.append(_f("S1", ep,
                                       f"index span {span} != meta length {e['length']}",
                                       {"span": span, "meta_length": e["length"]}))
    # 대표 카메라 외 카메라의 파일 부재 (보강: 멀티 카메라)
    # 전 에피소드 부재 = 데이터셋 단위 1건 (부분 복사본이든 결함이든 명시),
    # 일부 부재 = 에피소드 단위 (대표 카메라와 같은 방식).
    for key in reader.video_keys:
        if key == reader.video_key:
            continue
        missing = [e["episode_index"] for e in eps
                   if e.get("cameras", {}).get(key, {}).get("path") is None
                   or not e["cameras"][key]["path"].exists()]
        if len(missing) == len(eps) and eps:
            findings.append(_f("S1", None,
                               f"camera '{key}' declared but no video files present "
                               f"for any of {len(eps)} episodes",
                               {"camera": key, "episodes_missing": len(missing)}))
        else:
            for ep in missing:
                findings.append(_f("S1", ep,
                                   f"missing video file for camera '{key}'",
                                   {"camera": key}))
    if reader.version == "v3.0":
        ordered = sorted(eps, key=lambda x: x["episode_index"])
        expect = 0
        for e in ordered:
            if e["from_index"] != expect:
                findings.append(_f("S1", e["episode_index"],
                                   f"from_index {e['from_index']} != expected contiguous {expect}",
                                   {"from_index": e["from_index"], "expected": expect}))
            expect = e["to_index"]
        try:
            total = reader.total_data_rows()
            if expect != total:
                findings.append(_f("S1", None,
                                   f"last to_index {expect} != total data rows {total}",
                                   {"last_to_index": expect, "total_rows": total}))
        except Exception:
            pass
    return findings


def check_s2(ctx: Ctx):
    """차원·스키마 정합성 + 값 유효성(NaN/Inf — 기존 nan 검사 편입)."""
    findings = []
    reader = ctx.reader
    feats = reader.info.get("features", {})
    for key in ("observation.state", "action"):
        if key not in feats:
            findings.append(_f("S2", None, f"feature '{key}' missing from info.json features"))
    video_feats = [k for k, v in feats.items()
                   if isinstance(v, dict) and v.get("dtype") in ("video", "image")]
    if not video_feats:
        findings.append(_f("S2", None, "no video/image feature declared in info.json features"))
    declared = {}
    for key in ("observation.state", "action"):
        if key in feats and feats[key].get("shape"):
            declared[key] = int(feats[key]["shape"][0])
    required_cols = {"episode_index", "frame_index", "timestamp",
                     "observation.state", "action"}
    seen_cols = set()
    dim_mismatch = {}  # key -> {"declared":, "actual":, "episodes": [...]}
    for e in reader.episodes:
        ep = e["episode_index"]
        try:
            cols = set(reader.data_columns(e))
            d = reader.episode_data(e)
        except Exception:
            continue  # 읽기 실패는 S1 담당
        seen_cols |= cols
        for key, arr in (("observation.state", d["state"]), ("action", d["action"])):
            if key in declared and arr.shape[1] != declared[key]:
                m = dim_mismatch.setdefault(key, {"declared": declared[key],
                                                  "actual": int(arr.shape[1]),
                                                  "episodes": []})
                m["episodes"].append(ep)
        bad_parts, evidence = [], {}
        for col in ("state", "action"):
            bad = ~np.isfinite(d[col])
            if bad.any():
                idx = int(np.argwhere(bad)[0][0])
                bad_parts.append(f"{col}: {int(bad.sum())} non-finite, first at frame {idx}")
                evidence[col] = {"non_finite": int(bad.sum()), "first_frame": idx}
        if bad_parts:
            findings.append(_f("S2", ep, "; ".join(bad_parts), evidence))
    # 차원 불일치는 선언 오류 1건으로 집계 (에피소드마다 같은 선언을 참조하므로)
    for key, m in dim_mismatch.items():
        findings.append(_f("S2", None,
                           f"{key} dim {m['actual']} != declared shape {m['declared']} "
                           f"in {len(m['episodes'])} episodes",
                           {"declared": m["declared"], "actual": m["actual"],
                            "episodes_affected": len(m["episodes"]),
                            "episodes": m["episodes"][:20]}))
    missing_cols = required_cols - seen_cols
    if missing_cols and reader.episodes:
        findings.append(_f("S2", None,
                           f"required data columns missing: {sorted(missing_cols)}",
                           {"missing_columns": sorted(missing_cols)}))
    return findings


def check_s3(ctx: Ctx):
    """시간축: 역전·중복(기존 timestamp) + 끊김(gap) + fps 간격 정합성."""
    findings = []
    reader = ctx.reader
    fps = float(reader.info.get("fps", 0)) or None
    for e in reader.episodes:
        ep = e["episode_index"]
        try:
            d = reader.episode_data(e)
        except Exception:
            continue
        ts = d["timestamp"]
        if len(ts) < 2:
            continue
        diffs = np.diff(ts)
        bad = np.nonzero(diffs <= 0)[0]
        if len(bad):
            findings.append(_f("S3", ep,
                               f"{len(bad)} non-increasing steps, first at frame {int(bad[0])} "
                               f"({ts[bad[0]]:.3f} -> {ts[bad[0] + 1]:.3f})",
                               {"non_increasing": int(len(bad)), "first_frame": int(bad[0])}))
        if fps:
            gaps = np.nonzero(diffs > TH["gap_factor"] / fps)[0]
            if len(gaps):
                findings.append(_f("S3", ep,
                                   f"{len(gaps)} timestamp gaps > {TH['gap_factor'] / fps:.3f}s, "
                                   f"max gap {float(diffs.max()):.3f}s",
                                   {"gaps": int(len(gaps)), "max_gap_s": float(diffs.max())}))
            med = float(np.median(diffs))
            if abs(med - 1.0 / fps) > TH["fps_tol"] / fps:
                findings.append(_f("S3", ep,
                                   f"median interval {med:.4f}s != 1/fps {1.0 / fps:.4f}s",
                                   {"median_interval_s": med, "expected_s": 1.0 / fps}))
    return findings


# ---------------- 영상 ----------------

def check_v1(ctx: Ctx):
    """검은 화면 / 정지 화면. 선언된 모든 카메라를 감사한다."""
    findings = []
    for key in ctx.reader.video_keys:
        for e in ctx.reader.episodes:
            ep = e["episode_index"]
            st = ctx.video_stats(e, key)
            if st is None:
                continue  # 파일 없음은 S1 담당
            if st["brightness"] < TH["black_brightness"]:
                findings.append(_f("V1", ep,
                                   f"black video [{key}]: mean brightness {st['brightness']:.2f} < {TH['black_brightness']}",
                                   {"camera": key,
                                    "mean_brightness": round(st["brightness"], 3)}))
            if st["pair_diffs"]:
                same = sum(1 for x in st["pair_diffs"] if x < TH["static_diff"])
                ratio = same / len(st["pair_diffs"])
                if ratio >= TH["static_ratio"]:
                    findings.append(_f("V1", ep,
                                       f"static video [{key}]: {ratio:.0%} of consecutive frame pairs are identical",
                                       {"camera": key,
                                        "identical_ratio": round(ratio, 3)}))
    return findings


def check_v2(ctx: Ctx):
    """흔들림(에피소드 프레임간 차이 분포 전체의 들뜸) / 흐림(라플라시안 분산 붕괴).
    데이터셋 상대 판정을 카메라별로 계산한다. 흔들림 규칙은 4단계에서
    max 기반에서 중앙값 기반으로 교체."""
    findings = []
    for key in ctx.reader.video_keys:
        stats = {}
        for e in ctx.reader.episodes:
            st = ctx.video_stats(e, key)
            if st is not None:
                stats[e["episode_index"]] = st
        if not stats:
            continue
        lap_median_all = float(np.median([s["lap_median"] for s in stats.values()]))
        # 표본 모드에서는 쌍 차이가 step프레임 간격이라 프레임당으로 나눠
        # 정규화한다 (간격이 에피소드마다 달라 정규화 없이는 전수 결과와
        # 비교가 안 되고, 절대 가드 40이 무의미해져 전 에피소드 오탐이 난다).
        def _norm_diffs(s):
            step = s.get("sample_step", 1)
            if step > 1:
                return [d / step for d in s["pair_diffs"]]
            return s["pair_diffs"]
        med_diff_all = float(np.median(
            [float(np.median(_norm_diffs(s))) for s in stats.values()
             if s["pair_diffs"]])) if any(s["pair_diffs"] for s in stats.values()) else 0.0
        for ep, st in stats.items():
            if lap_median_all > 0 and st["lap_median"] < TH["blur_ratio"] * lap_median_all:
                findings.append(_f("V2", ep,
                                   f"blurry video [{key}]: median Laplacian variance {st['lap_median']:.2f} "
                                   f"< {TH['blur_ratio']} x dataset median {lap_median_all:.2f}",
                                   {"camera": key,
                                    "lap_median": round(st["lap_median"], 3),
                                    "dataset_lap_median": round(lap_median_all, 3)}))
            diffs = _norm_diffs(st)
            if diffs:
                # 4단계 교체: 기존 '최대 프레임쌍 차이 vs 에피소드 중앙값' 규칙은
                # 조용한 실영상에서 빠른 동작 한 순간에 전 에피소드 오탐을 냈다.
                # 흔들림은 분포 전체가 들뜨는 현상으로 보고, 에피소드 중앙 차이를
                # 데이터셋 중앙값과 비교한다. 단일 프레임쌍의 극단값은 별도 가드.
                ep_med = float(np.median(diffs))
                mx = float(np.max(diffs))
                if (ep_med > TH["shake_ratio"] * med_diff_all
                        and ep_med > TH["shake_median_abs"]):
                    findings.append(_f("V2", ep,
                                       f"unstable video [{key}]: median frame diff {ep_med:.2f} > "
                                       f"{TH['shake_ratio']} x dataset median {med_diff_all:.2f}",
                                       {"camera": key,
                                        "median_diff": round(ep_med, 3),
                                        "dataset_median_diff": round(med_diff_all, 3)}))
                elif mx > TH["shake_single_abs"]:
                    findings.append(_f("V2", ep,
                                       f"unstable video [{key}]: single frame diff {mx:.2f} > "
                                       f"{TH['shake_single_abs']} (gross glitch guard)",
                                       {"camera": key,
                                        "max_diff": round(mx, 3)}))
    return findings


def check_v3(ctx: Ctx):
    """에피소드 길이 이상: 영상 프레임 수(카메라별) vs 메타 길이, 길이 분포 이탈."""
    findings = []
    lengths = [e["length"] for e in ctx.reader.episodes]
    med_len = float(np.median(lengths)) if lengths else 0
    for key in ctx.reader.video_keys:
        for e in ctx.reader.episodes:
            ep = e["episode_index"]
            st = ctx.video_stats(e, key)
            if st is not None and st["n_frames"] != e["length"]:
                findings.append(_f("V3", ep,
                                   f"video frames [{key}] {st['n_frames']} != meta length {e['length']}",
                                   {"camera": key,
                                    "video_frames": st["n_frames"],
                                    "meta_length": e["length"]}))
    for e in ctx.reader.episodes:
        ep = e["episode_index"]
        if med_len > 0:
            ratio = e["length"] / med_len
            if ratio >= TH["len_ratio"] or ratio <= 1.0 / TH["len_ratio"]:
                findings.append(_f("V3", ep,
                                   f"episode length {e['length']} is {ratio:.2f}x the median length {med_len:.0f}",
                                   {"length": e["length"], "median_length": med_len,
                                    "ratio": round(ratio, 3)}))
    return findings


# ---------------- 행동 ----------------

def _columns(d):
    """(이름, 배열) 목록: observation.state[i], action[i]."""
    out = []
    for j in range(d["state"].shape[1]):
        out.append((f"observation.state[{j}]", d["state"][:, j]))
    for j in range(d["action"].shape[1]):
        out.append((f"action[{j}]", d["action"][:, j]))
    return out


def check_a1(ctx: Ctx):
    """범위 이탈: 다른 에피소드들의 값 범위를 크게 벗어난 값이 많은 에피소드.

    물리 범위가 메타에 선언돼 있지 않으므로, 판정 대상 에피소드를 뺀
    나머지 에피소드 풀링 분포의 [q0.1%, q99.9%]를 '정상 대역'으로 삼는다
    (leave-one-out). 3단계의 풀링 Tukey 울타리는 실데이터의 다봉 분포
    (그리퍼 개폐, 작업 단계별 자세)에서 전 에피소드에 오탐을 냈고,
    풀링 분위수 대역은 결함 에피소드 자체가 대역을 밀어 올리는 문제가 있어
    4단계에서 LOO로 교체했다. 근거: stage4_results.md.
    """
    findings = []
    per_ep = {}
    for e in ctx.reader.episodes:
        try:
            per_ep[e["episode_index"]] = ctx.reader.episode_data(e)
        except Exception:
            continue
    cols_by_ep = {ep: dict(_columns(d)) for ep, d in per_ep.items()}
    if not cols_by_ep:
        return findings
    col_names = list(next(iter(cols_by_ep.values())).keys())
    bands = {}
    for name in col_names:
        for ep in cols_by_ep:
            others = [cols_by_ep[o][name] for o in cols_by_ep if o != ep]
            if not others:  # 에피소드가 1개뿐이면 자기 자신으로 대역 산정
                others = [cols_by_ep[ep][name]]
            parts = [o[np.isfinite(o)] for o in others]
            parts = [p for p in parts if p.size]
            if not parts:
                continue
            vals = np.concatenate(parts)
            lo, hi = np.quantile(vals, [TH["range_qlo"], TH["range_qhi"]])
            q25, q75 = np.quantile(vals, [0.25, 0.75])
            margin = TH["range_band_margin"] * float(q75 - q25)
            bands[(ep, name)] = (float(lo - margin), float(hi + margin))
    for ep, d in per_ep.items():
        offenders = {}
        for name, col in _columns(d):
            if (ep, name) not in bands:
                continue
            lo, hi = bands[(ep, name)]
            finite = col[np.isfinite(col)]
            if finite.size == 0:
                continue
            frac = float(np.mean((finite < lo) | (finite > hi)))
            if frac > TH["range_frac"]:
                offenders[name] = {"outside_frac": round(frac, 3),
                                   "band": [round(lo, 3), round(hi, 3)],
                                   "observed_min": round(float(finite.min()), 3),
                                   "observed_max": round(float(finite.max()), 3)}
        if offenders:
            names = ", ".join(offenders.keys())
            findings.append(_f("A1", ep,
                               f"values outside leave-one-out band in {names}",
                               {"columns": offenders}))
    return findings


def _dim_name(reader, feature_key, dim):
    """info.features[feature_key].names에서 차원 이름을 해석한다.
    v2.1은 문자열 리스트, v3.0은 {"motors": [...]} 형태도 있어 둘 다 대응하고,
    해석할 수 없으면 '키[차원]' 표기로 떨어진다."""
    feats = reader.info.get("features", {})
    names = feats.get(feature_key, {}).get("names")
    if isinstance(names, dict):
        for v in names.values():
            if isinstance(v, list) and dim < len(v):
                return str(v[dim])
    elif isinstance(names, list) and dim < len(names):
        return str(names[dim])
    return f"{feature_key}[{dim}]"


def _interval_evidence(ctx: Ctx, d, frame):
    """A2 증거(0.3.0): 점프 구간 간격 비율. 증거 전용 — 처분에 쓰지 않는다.

    타임스탬프가 정보성(격자가 아님)일 때만 계산한다. 격자 데이터에서는
    비율이 항상 1.0이라 원인 정보를 담을 수 없기 때문이다
    (a2_interval_test/RESULTS.md). frame은 np.diff 인덱스 — 점프는
    row frame과 row frame+1 사이에 있다 (기존 A2와 같은 규약).
    """
    diag = ctx.timestamp_grid()
    if not diag.get("informative"):
        note = ("timestamps are a synthetic grid (frame_index/fps); "
                "interval ratio not applicable") if diag.get("is_grid") else \
               ("timestamp informativeness could not be assessed; "
                "interval ratio not computed")
        return {"interval_ratio": None, "interval_class": None,
                "interval_note": note}
    ts = np.asarray(d["timestamp"], dtype=np.float64)
    diffs = np.diff(ts)
    if frame >= len(diffs):
        return {"interval_ratio": None, "interval_class": None,
                "interval_note": "no interval at the jump frame"}
    normal = float(np.median(diffs))
    if not np.isfinite(normal) or normal <= 0:
        return {"interval_ratio": None, "interval_class": None,
                "interval_note": "episode median interval is not positive"}
    jump_iv = float(diffs[frame])
    ratio = jump_iv / normal
    if ratio >= TH["interval_drop_ratio"]:
        cls = "dropped-frame-looking"
    elif TH["interval_normal_lo"] <= ratio < TH["interval_normal_hi"]:
        cls = "normal-interval"
    else:
        cls = "ambiguous"
    return {"jump_interval_s": round(jump_iv, 6),
            "normal_interval_s": round(normal, 6),
            "interval_ratio": round(ratio, 4),
            "interval_class": cls}


def _state_evidence(ctx: Ctx, d, col_name, frame):
    """A2 증거(0.3.0): 지배 차원 + observation.state 추종 여부. 증거 전용.

    방법은 a2_interval_test/followup_analyze.py와 동일하다: 점프 프레임의
    지배 차원(스텝 절댓값이 가장 큰 차원)에서, state의 동시 스텝과 착지 후
    10프레임 내 최대 이탈(점프 전 state 기준)을 재고, 지배 차원 action
    스텝의 50%를 기준으로 state-simultaneous/follows/absent로 표기한다.
    state 열 자체의 점프는 '명령에 대한 상태 추종' 개념이 성립하지 않아
    지배 차원만 기록하고 라벨은 비운다.
    """
    arr = d[col_name].astype(np.float64)
    land = frame + 1
    if land < 1 or land >= len(arr):
        return {}
    step_vec = arr[land] - arr[land - 1]
    dim = int(np.argmax(np.abs(step_vec)))
    feat_key = "action" if col_name == "action" else "observation.state"
    ev = {"dominant_dim": dim,
          "dominant_dim_name": _dim_name(ctx.reader, feat_key, dim)}
    if col_name != "action":
        ev["state_label"] = None
        ev["state_note"] = ("state-following evidence applies to "
                            "action-command jumps; this jump is in "
                            "observation.state itself")
        return ev
    sta = d["state"].astype(np.float64)
    a_step = abs(float(step_vec[dim]))
    s_step = float(sta[land, dim] - sta[land - 1, dim])
    win_end = min(land + 10, len(sta) - 1)
    window = sta[land:win_end + 1, dim]
    excursion = float(np.max(np.abs(window - sta[land - 1, dim])))
    follow = float(np.max(np.abs(window - sta[land, dim])))
    ev.update({
        "dominant_step": round(a_step, 4),
        "state_step_at_jump": round(s_step, 4),
        "state_max_follow_10f": round(follow, 4),
        "state_max_excursion_10f": round(excursion, 4),
        "state_follow_fraction": round(excursion / a_step, 3)
        if a_step > 0 else None,
    })
    if a_step <= 0:
        ev["state_label"] = None
    elif abs(s_step) >= TH["state_follow_frac"] * a_step:
        ev["state_label"] = "state-simultaneous"
    elif excursion >= TH["state_follow_frac"] * a_step:
        ev["state_label"] = "state-follows"
    else:
        ev["state_label"] = "state-absent"
    return ev


def check_a2(ctx: Ctx):
    """급격한 점프: 프레임간 스텝(L2)이 중앙값의 5배를 넘고, 데이터셋 전체
    스텝 분포 기준으로도 극단적인 순간이동.

    4단계 조정: 절대 하한 1.0은 단위(라디안/도)에 따라 무의미해, 하한을
    max(1.0, 3 × 데이터셋 풀링 스텝 q99)로 바꿨다. 실데이터 표본 판정에서
    기존 규칙의 검출 88건이 전부 '스텝형'(점프 후 유지 — 프레임 드롭·빠른
    동작으로 보임)이었고 스파이크형(글리치)은 0건이었다. 근거: stage4_results.md.

    0.3.0: 검출 규칙은 그대로 두고 finding에 증거만 덧붙인다 — 게이트된
    간격 비율(_interval_evidence)과 state 추종(_state_evidence). 점수·처분
    산정에는 새 증거를 쓰지 않는다.
    """
    findings = []
    per = []  # (ep, col_name, steps)
    pooled = {"state": [], "action": []}
    ep_data = {}
    for e in ctx.reader.episodes:
        ep = e["episode_index"]
        try:
            d = ctx.reader.episode_data(e)
        except Exception:
            continue
        ep_data[ep] = d
        for col_name in ("state", "action"):
            arr = d[col_name].astype(np.float64)
            if len(arr) < 2:
                continue
            steps = np.linalg.norm(np.diff(arr, axis=0), axis=1)
            finite = np.isfinite(steps)
            if not finite.any():
                continue
            per.append((ep, col_name, steps, finite))
            pooled[col_name].append(steps[finite])
    floors = {}
    for col_name, parts in pooled.items():
        if parts:
            q99 = float(np.quantile(np.concatenate(parts), 0.99))
            floors[col_name] = max(TH["jump_abs"],
                                   TH["jump_dataset_factor"] * q99)
    for ep, col_name, steps, finite in per:
        steps_f = steps[finite]
        med = float(np.median(steps_f))
        mx = float(np.max(steps_f))
        floor = floors.get(col_name, TH["jump_abs"])
        if mx > TH["jump_factor"] * med and mx > floor:
            frame = int(np.nonzero(finite)[0][int(np.argmax(steps_f))])
            evidence = {"column": col_name, "max_step": round(mx, 4),
                        "median_step": round(med, 4),
                        "dataset_floor": round(floor, 4), "frame": frame}
            evidence.update(_interval_evidence(ctx, ep_data[ep], frame))
            evidence.update(_state_evidence(ctx, ep_data[ep], col_name, frame))
            findings.append(_f("A2", ep,
                               f"{col_name}: max step {mx:.3f} > {TH['jump_factor']} x median step "
                               f"{med:.3f} and > dataset floor {floor:.3f} at frame {frame}",
                               evidence))
    return findings


def check_a3(ctx: Ctx):
    """무동작 차원: 에피소드 내내 표준편차 0인 차원 (그리퍼 등)."""
    findings = []
    for e in ctx.reader.episodes:
        ep = e["episode_index"]
        try:
            d = ctx.reader.episode_data(e)
        except Exception:
            continue
        dead = []
        for name, col in _columns(d):
            finite = col[np.isfinite(col)]
            if finite.size and float(np.std(finite)) < TH["dead_std"]:
                dead.append(name)
        if dead:
            findings.append(_f("A3", ep,
                               f"no-motion dimensions: {', '.join(dead)}",
                               {"dead_columns": dead}))
    return findings


def check_a4(ctx: Ctx):
    """중복 에피소드: state+action 궤적 해시가 같은 에피소드 쌍."""
    import hashlib
    findings = []
    seen = {}
    for e in sorted(ctx.reader.episodes, key=lambda x: x["episode_index"]):
        ep = e["episode_index"]
        try:
            d = ctx.reader.episode_data(e)
        except Exception:
            continue
        h = hashlib.sha256(
            np.round(d["state"], 5).tobytes() + np.round(d["action"], 5).tobytes()
        ).hexdigest()
        if h in seen:
            findings.append(_f("A4", ep,
                               f"duplicate trajectory of episode {seen[h]}",
                               {"duplicate_of": seen[h], "trajectory_hash": h[:12]}))
        else:
            seen[h] = ep
    return findings


# ---------------- 지시문 ----------------

def check_l1(ctx: Ctx):
    """지시문 누락(에피소드별) / 전부 동일(데이터셋)."""
    findings = []
    distinct = set()
    for e in ctx.reader.episodes:
        ep = e["episode_index"]
        tasks = [t for t in e.get("tasks", []) if str(t).strip()]
        if not tasks:
            findings.append(_f("L1", ep, "no task instruction for this episode"))
        distinct.update(tasks)
    n = len(ctx.reader.episodes)
    declared = ctx.reader.info.get("total_tasks")
    # 단일 태스크로 선언된 데이터셋(total_tasks<=1)은 전부 동일이 설계상 정상이라 제외.
    # 선언은 여러 개인데 실제 사용은 1개뿐일 때만 결함으로 본다 (4단계 조정).
    if n > 1 and len(distinct) == 1 and (declared is None or int(declared) > 1):
        findings.append(_f("L1", None,
                           f"all {n} episodes share a single task: '{next(iter(distinct))}'",
                           {"distinct_tasks": 1, "episodes": n}))
    if n > 0 and len(distinct) == 0:
        findings.append(_f("L1", None, "no task instructions in the whole dataset",
                           {"distinct_tasks": 0, "episodes": n}))
    return findings


def check_l2(ctx: Ctx):
    """성공/실패 표시 없음: 에피소드 메타에 success/failure 계열 필드가 없음."""
    if not ctx.reader.has_success_labels():
        return [_f("L2", None,
                   "no success/failure label found in episode metadata "
                   "(failed episodes cannot be told apart)",
                   {"episodes": len(ctx.reader.episodes)})]
    return []


CHECKS12 = {
    "S1": check_s1, "S2": check_s2, "S3": check_s3,
    "V1": check_v1, "V2": check_v2, "V3": check_v3,
    "A1": check_a1, "A2": check_a2, "A3": check_a3, "A4": check_a4,
    "L1": check_l1, "L2": check_l2,
}
