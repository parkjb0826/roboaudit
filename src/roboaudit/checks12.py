"""RoboAudit 검사 17종 (설계서 v1, 4절 + 0.3.2 확장).

구조 S1 메타·파일 무결성(치명) / S2 차원·스키마·값 유효성(치명) / S3 시간축(경고)
     S4 기록 통계 드리프트(경고) / S5 라이선스·카드 기본값(참고)
영상 V1 검은·정지 화면(치명) / V2 흔들림·흐림(경고) / V3 에피소드 길이 이상(경고)
행동 A1 범위 이탈(치명) / A2 급격한 점프(경고) / A3 무동작 차원(경고) / A4 중복 에피소드(참고)
     A5 근접 중복 에피소드(참고) / A6 에피소드 정지 비율(경고)
     A7 리더·팔로워 캘리브레이션 드리프트(경고)
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

0.3.1 변경 (전부 증거 전용 — 검출·점수·처분 규칙은 바꾸지 않는다):
- 진단은 두 축(clock_provenance × interval_regularity)으로 분리됐고,
  frame_index 빈틈은 인덱스 유래 별도 신호로 보고된다 (diagnostics.py).
  A2 증거: 점프 지점에 인덱스 빈틈이 있으면 index_gap_at_jump을 출처
  표기와 함께 덧붙인다. 게이트는 실제 시계일 때만 열리며, 인덱스 유래
  비율이 normal-interval로 표기되는 일은 없다.
- state-absent는 '빠른 명령' 쪽으로 기운 판정이 아니라 미해결(unresolved)
  로 명시한다 (state_note).

0.3.2 변경 (신규 검사 5종 — 전부 규칙+임계값, 임계값은 전부 provisional):
- S4 기록 통계 드리프트: meta/stats.json(v3.0) 또는 episodes_stats.jsonl
  (v2.1)의 기록 통계와 실제 데이터 재계산 통계를 결정적으로 비교한다.
  기준은 kinema·lerobot-doctor가 공개한 것과 같은 계열 — 평균 이동
  0.1σ 초과 또는 표준편차 10% 초과 상대 변화 (근거: research 보고서 #1).
- S5 라이선스·카드 기본값(기본형): README.md 카드의 license 필드 부재,
  또는 LeRobot 카드 템플릿 기본값(apache-2.0) 그대로인 경우를 참고급
  으로 알린다. 원본 대조 같은 큰 기능은 하지 않는다.
- A5 근접 중복: A4(정확 해시)가 놓치는 '살짝 다른 복사본'을 16점
  재표본 궤적의 σ 정규화 거리로 잡는다 (방법은 결정적, 허용오차 provisional).
- A6 에피소드 정지 비율: 에피소드 단위 정지 프레임 비율과 시작 정지를
  본다 (A3는 차원 단위라 에피소드 단위 정지는 못 봤다).
- A7 캘리브레이션 드리프트: state와 action의 차원·이름이 같을 때만,
  action−state 중앙값 오프셋이 state 표준편차의 절반을 넘는 체계적
  편향을 데이터셋 단위로 보고한다 (리더/팔로워 정렬 문제의 신호).
"""
from pathlib import Path

import cv2
import numpy as np

from .reader import DatasetReader

RULES_VERSION = "rules-2026-11-23.1"

SEVERITY = {
    "S1": "critical", "S2": "critical", "S3": "warning",
    "S4": "warning", "S5": "info",
    "V1": "critical", "V2": "warning", "V3": "warning",
    "A1": "critical", "A2": "warning", "A3": "warning", "A4": "info",
    "A5": "info", "A6": "warning", "A7": "warning",
    "L1": "warning", "L2": "info",
}
CHECK_NAMES = {
    "S1": "메타·파일 무결성", "S2": "차원·스키마 정합성", "S3": "시간축",
    "S4": "기록 통계 드리프트", "S5": "라이선스·카드 기본값",
    "V1": "검은·정지 화면", "V2": "흔들림·흐림", "V3": "에피소드 길이 이상",
    "A1": "범위 이탈", "A2": "급격한 점프", "A3": "무동작 차원",
    "A4": "중복 에피소드", "A5": "근접 중복 에피소드",
    "A6": "에피소드 정지 비율", "A7": "캘리브레이션 드리프트",
    "L1": "지시문 누락·전부 동일", "L2": "성공·실패 표시 없음",
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
    # --- 0.3.2 신규 검사 (전부 provisional — 실데이터 표본으로 재검증 필요) ---
    "stats_mean_shift": 0.1,         # S4: |기록 평균 - 실제 평균| > 이 값 × 기록 std 이면 드리프트 (kinema 공개 기준과 같은 계열)
    "stats_std_shift": 0.1,          # S4: std 상대 변화 > 이 비율이면 드리프트
    "calib_offset_ratio": 0.5,       # A7: |중앙값 오프셋| > 이 비율 × state std 인 차원이 있으면 보고
    "calib_report_ratio": 0.25,      # A7: 증거에 싣는 차원의 하한 비율
    "idle_step_eps": 1e-6,           # A6: state+action 스텝 L2 합이 이 값 이하이면 정지 프레임으로 간주 (사실상 완전 반복)
    "idle_ratio": 0.30,              # A6: 에피소드 정지 비율이 이 값 이상이면 발견
    "idle_leading_ratio": 0.20,      # A6: 시작 정지 비율이 이 값 이상이면 발견 (녹화 시작 패딩)
    "neardup_points": 16,            # A5: 궤적 재표본 점 수
    "neardup_mean_tol": 0.01,        # A5: σ 정규화 평균 절댓값 차이 허용오차
    "neardup_max_tol": 0.05,         # A5: σ 정규화 최대 절댓값 차이 허용오차
    "neardup_len_tol": 0.05,         # A5: 길이 차이가 이 비율을 넘는 쌍은 비교하지 않음
}


def _f(check, episode_index, detail, evidence=None):
    return {"check": check, "severity": SEVERITY[check],
            "episode_index": episode_index, "detail": detail,
            "evidence": evidence or {}}


class Ctx:
    """검사 실행 컨텍스트: 리더 + 영상 통계 캐시 (카메라별)."""

    def __init__(self, root: Path, sample_frames=None, max_episodes=None):
        self.root = root
        self.reader = DatasetReader(root, sample_frames=sample_frames,
                                    max_episodes=max_episodes)
        self._vstats = {}
        self._ts_grid = None

    def timestamp_grid(self):
        """타임스탬프 격자 진단 (diagnostics.py). 감사당 1회만 계산해 캐시한다.
        검사가 아니며 점수·처분에 쓰이지 않는다 — A2 증거 게이트와
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
    # 에피소드 표본 감사(--max-episodes)에서는 선언 총량과 비교할 수 없다:
    # 총량 대조 2건과 v3.0 연속성 대조는 표본일 때 건너뛴다 (표본 고지 참조).
    sampled = getattr(reader, "episode_sampled", False)
    if not sampled and len(eps) != int(info.get("total_episodes", -1)):
        findings.append(_f("S1", None,
                           f"episode count {len(eps)} != total_episodes {info.get('total_episodes')}",
                           {"meta_episodes": len(eps),
                            "total_episodes": info.get("total_episodes")}))
    sum_len = sum(e["length"] for e in eps)
    if not sampled and int(info.get("total_frames", sum_len)) != sum_len:
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
    if reader.version == "v3.0" and not sampled:
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


# ---------------- 기록 통계·라이선스 (0.3.2) ----------------

_STATS_FEATURES = (("observation.state", "state"), ("action", "action"))


def _stat_drift_dims(recorded, actual):
    """기록 통계 1피처 vs 재계산 배열: 임계를 넘는 차원 목록.

    평균 이동은 기록 std(σ) 단위, std 변화는 상대 비율로 잰다. 재계산은
    ddof=0 — LeRobot의 통계 산출 관행과 같다.
    """
    rec_mean = recorded.get("mean")
    rec_std = recorded.get("std")
    if rec_mean is None or rec_std is None or actual.size == 0:
        return []
    if len(rec_mean) != actual.shape[1] or len(rec_std) != actual.shape[1]:
        return []  # 차원 자체가 다르면 S2 담당
    act_mean = actual.mean(axis=0)
    act_std = actual.std(axis=0)
    out = []
    for j in range(actual.shape[1]):
        rm, rs = float(rec_mean[j]), float(rec_std[j])
        am, asd = float(act_mean[j]), float(act_std[j])
        if rs > 1e-12:
            mean_shift = abs(am - rm) / rs
            std_rel = abs(asd - rs) / rs
        else:
            mean_shift = abs(am - rm)
            std_rel = 0.0 if asd <= 1e-12 else float("inf")
        if mean_shift > TH["stats_mean_shift"] or std_rel > TH["stats_std_shift"]:
            out.append({"dim": j, "recorded_mean": round(rm, 6),
                        "actual_mean": round(am, 6),
                        "mean_shift_sigma": round(mean_shift, 4),
                        "recorded_std": round(rs, 6),
                        "actual_std": round(asd, 6),
                        "std_rel_change": round(std_rel, 4)})
    return out


def _recorded_count(rec_feat):
    cnt = rec_feat.get("count")
    if isinstance(cnt, (list, tuple)):
        return int(cnt[0]) if cnt else None
    return int(cnt) if cnt is not None else None


def check_s4(ctx: Ctx):
    """기록 통계 드리프트: 메타에 기록된 정규화 통계 vs 실제 데이터 재계산.

    통계를 다시 만들지 않고 데이터만 고치면 기록 통계가 낡고, 학습 때
    정규화가 조용히 틀어진다 (kinema·lerobot-doctor가 공통으로 잡는
    결함). 비교 대상은 observation.state·action뿐이다 (영상 통계는
    재계산하지 않는다). 기록이 두 층으로 있으면 둘 다 본다:
    데이터셋 단위(meta/stats.json — 실제로 정규화에 쓰이는 파일)와
    에피소드 단위(v2.1 episodes_stats.jsonl / v3.0 에피소드 메타 통계 열).
    에피소드 표본 감사에서는 데이터셋 단위 비교를 건너뛴다 (표본의
    분포는 전체 분포와 다를 수 있기 때문이다). 데이터셋 단위 1건으로
    보고한다.
    """
    reader = ctx.reader
    src = reader.recorded_stats()
    if src is None:
        return []  # 기록 통계 없음 — 검사 상태는 not_applicable로 표시된다
    sampled = getattr(reader, "episode_sampled", False)
    per_ep_data = {}
    for e in reader.episodes:
        try:
            per_ep_data[e["episode_index"]] = reader.episode_data(e)
        except Exception:
            continue
    if not per_ep_data:
        return []
    evidence = {"thresholds": {"mean_shift_sigma": TH["stats_mean_shift"],
                               "std_rel_change": TH["stats_std_shift"]},
                "sources": []}
    notes = []
    # --- 에피소드 단위 기록 ---
    if src.get("per_episode"):
        evidence["sources"].append(src.get("source_per_episode"))
        drifted = {}
        feat_ev = {}
        for ep, rec in sorted(src["per_episode"].items()):
            if ep not in per_ep_data:
                continue
            d = per_ep_data[ep]
            for feat, key in _STATS_FEATURES:
                if feat not in rec:
                    continue
                dims = _stat_drift_dims(rec[feat],
                                        d[key].astype(np.float64))
                cnt = _recorded_count(rec[feat])
                if dims or (cnt is not None and cnt != len(d[key])):
                    drifted.setdefault(ep, []).append(feat)
                    ev = feat_ev.setdefault(feat, {"episodes_drifted": []})
                    ev["episodes_drifted"].append(ep)
                    if dims:
                        ev["max_mean_shift_sigma"] = max(
                            ev.get("max_mean_shift_sigma", 0.0),
                            max(x["mean_shift_sigma"] for x in dims))
                        ev.setdefault("worst_dims", dims[:4])
        if drifted:
            eps_list = sorted(drifted)
            evidence["per_episode"] = {
                "features": feat_ev,
                "episodes_drifted": eps_list[:50],
                "episodes_drifted_total": len(eps_list)}
            notes.append(f"per-episode recorded stats drift in "
                         f"{len(eps_list)} episodes (first: {eps_list[:5]})")
    # --- 데이터셋 단위 기록 (stats.json) ---
    if src.get("dataset") is not None and not sampled:
        evidence["sources"].append(src.get("source_dataset"))
        feat_ev = {}
        for feat, key in _STATS_FEATURES:
            rec = src["dataset"].get(feat)
            if rec is None:
                continue
            actual = np.concatenate(
                [per_ep_data[ep][key].astype(np.float64)
                 for ep in sorted(per_ep_data)])
            dims = _stat_drift_dims(rec, actual)
            cnt = _recorded_count(rec)
            count_bad = cnt is not None and cnt != len(actual)
            if not dims and not count_bad:
                continue
            ev = {"dims_drifted": dims[:8]}
            if dims:
                ev["max_mean_shift_sigma"] = max(
                    d["mean_shift_sigma"] for d in dims)
                ev["max_std_rel_change"] = max(
                    d["std_rel_change"] for d in dims)
                worst = max(dims, key=lambda d: d["mean_shift_sigma"])
                notes.append(
                    f"{feat} dim {worst['dim']}: mean shift "
                    f"{worst['mean_shift_sigma']:.2f}σ (recorded "
                    f"{worst['recorded_mean']} vs actual {worst['actual_mean']})")
            if cnt is not None:
                ev["count_recorded"] = cnt
                ev["count_actual"] = int(len(actual))
                if count_bad:
                    ev["count_mismatch"] = True
                    notes.append(f"{feat}: recorded count {cnt} != "
                                 f"actual rows {len(actual)}")
            feat_ev[feat] = ev
        if feat_ev:
            evidence["dataset_stats"] = {"features": feat_ev}
    if not notes:
        return []
    return [_f("S4", None,
               "recorded normalization stats drift from the actual data: "
               + "; ".join(notes[:4]), evidence)]


_LICENSE_TEMPLATE_DEFAULT = "apache-2.0"


def check_s5(ctx: Ctx):
    """라이선스·카드 기본값 (기본형): 카드의 license 필드 부재 또는
    LeRobot 템플릿 기본값(apache-2.0) 그대로인 경우를 참고급으로 알린다.

    근거: 2026-10 Hub LeRobot 데이터셋 3,000개 스캔(rdq 보고)에서
    56.5%가 템플릿 기본값을 그대로 달고 있었다 — 고른 게 아니라 안
    지운 값일 가능성이 높다. 카드 파일 자체가 로컬 복사본에 없으면
    (부분 복사본일 수 있어) 판단하지 않는다. 원본 데이터셋과의 대조
    같은 큰 기능은 하지 않는다.
    """
    card = ctx.reader.dataset_card()
    if card is None:
        return []
    licenses = card.get("licenses") or []
    if not licenses:
        return [_f("S5", None,
                   "dataset card (README.md) declares no license — "
                   "reuse terms are unstated",
                   {"card": card["path"], "license": None})]
    lowered = [str(x).strip().lower() for x in licenses]
    if all(x == _LICENSE_TEMPLATE_DEFAULT for x in lowered):
        return [_f("S5", None,
                   f"license '{licenses[0]}' is the LeRobot dataset-card "
                   "template default — it may never have been deliberately "
                   "chosen; verify it is intended",
                   {"card": card["path"], "license": licenses[0],
                    "template_default": _LICENSE_TEMPLATE_DEFAULT,
                    "note": "Oct 2026 scan of 3,000 Hub LeRobot datasets: "
                            "56.5% carried this template value (rdq)"})]
    return []


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


def _index_gap_at_jump(d, frame):
    """점프 지점의 frame_index 빈틈 (0.3.1, 별도 증거).

    인덱스 빈틈은 '기록 후 행 삭제'를 뜻하는 인덱스 유래 신호다. 시계
    증거가 아니므로 간격 비율 게이트와 합치지 않고, 비율·분류는 만들지
    않는다 — 특히 인덱스에서 도출한 비율이 normal-interval로 표기되는
    일은 없다. 빈틈이 없으면 None.
    """
    fi = np.asarray(d["frame_index"], dtype=np.int64)
    if frame + 1 >= len(fi):
        return None
    step = int(fi[frame + 1] - fi[frame])
    if step <= 1:
        return None
    return {"index_step": step, "missing_rows": step - 1,
            "meaning": "rows removed after recording",
            "provenance": "index-derived, not a clock"}


def _interval_evidence(ctx: Ctx, d, frame):
    """A2 증거(0.3.0): 점프 구간 간격 비율. 증거 전용 — 처분에 쓰지 않는다.

    타임스탬프가 정보성(실제 시계)일 때만 계산한다. 격자 데이터에서는
    비율이 항상 1.0이라 원인 정보를 담을 수 없기 때문이다
    (a2_interval_test/RESULTS.md). frame은 np.diff 인덱스 — 점프는
    row frame과 row frame+1 사이에 있다 (기존 A2와 같은 규약).

    0.3.1: 점프 지점에 frame_index 빈틈이 있으면 게이트와 무관하게
    index_gap_at_jump을 별도 증거로 덧붙인다 (출처: 인덱스 — 시계 아님).
    """
    gap = _index_gap_at_jump(d, frame)
    diag = ctx.timestamp_grid()
    if not diag.get("informative"):
        note = ("timestamps are a synthetic grid (frame_index/fps); "
                "interval ratio not applicable") if diag.get("is_grid") else \
               ("timestamp informativeness could not be assessed; "
                "interval ratio not computed")
        ev = {"interval_ratio": None, "interval_class": None,
              "interval_note": note}
        if gap is not None:
            ev["index_gap_at_jump"] = gap
            ev["interval_note"] = (
                note + "; a frame_index gap sits at this jump — reported "
                "as a separate index-derived signal (rows removed after "
                "recording), not as interval evidence")
        return ev
    ts = np.asarray(d["timestamp"], dtype=np.float64)
    diffs = np.diff(ts)
    if frame >= len(diffs):
        ev = {"interval_ratio": None, "interval_class": None,
              "interval_note": "no interval at the jump frame"}
        if gap is not None:
            ev["index_gap_at_jump"] = gap
        return ev
    normal = float(np.median(diffs))
    if not np.isfinite(normal) or normal <= 0:
        ev = {"interval_ratio": None, "interval_class": None,
              "interval_note": "episode median interval is not positive"}
        if gap is not None:
            ev["index_gap_at_jump"] = gap
        return ev
    jump_iv = float(diffs[frame])
    ratio = jump_iv / normal
    if ratio >= TH["interval_drop_ratio"]:
        cls = "dropped-frame-looking"
    elif TH["interval_normal_lo"] <= ratio < TH["interval_normal_hi"]:
        cls = "normal-interval"
    else:
        cls = "ambiguous"
    ev = {"jump_interval_s": round(jump_iv, 6),
          "normal_interval_s": round(normal, 6),
          "interval_ratio": round(ratio, 4),
          "interval_class": cls}
    if gap is not None:
        ev["index_gap_at_jump"] = gap
    return ev


def _state_evidence(ctx: Ctx, d, col_name, frame):
    """A2 증거(0.3.0): 지배 차원 + observation.state 추종 여부. 증거 전용.

    방법은 a2_interval_test/followup_analyze.py와 동일하다: 점프 프레임의
    지배 차원(스텝 절댓값이 가장 큰 차원)에서, state의 동시 스텝과 착지 후
    10프레임 내 최대 이탈(점프 전 state 기준)을 재고, 지배 차원 action
    스텝의 50%를 기준으로 state-simultaneous/follows/absent로 표기한다.
    state 열 자체의 점프는 '명령에 대한 상태 추종' 개념이 성립하지 않아
    지배 차원만 기록하고 라벨은 비운다.

    0.3.1: state-absent는 원인이 정해지지 않은 미해결(unresolved)이다 —
    state가 명령과 함께 뛰지도, 뒤따라오지도 않았다는 관찰일 뿐, '빠른
    명령이었다'는 쪽의 증거로 제시하지 않는다 (state_note로 명시).
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
        ev["state_note"] = ("unresolved: the state neither stepped with "
                            "the command nor followed within 10 frames. "
                            "This is an observation, not evidence for a "
                            "fast command or for a dropped frame.")
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

    0.3.1: 증거 보강만 추가 — 점프 지점의 인덱스 빈틈(index_gap_at_jump,
    별도 신호)과 state-absent의 미해결 명시(state_note). 검출 규칙·점수·
    처분은 그대로다.
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


def _traj_hash(d):
    import hashlib
    return hashlib.sha256(
        np.round(d["state"], 5).tobytes() + np.round(d["action"], 5).tobytes()
    ).hexdigest()


def check_a5(ctx: Ctx):
    """근접 중복: 정확히 같지는 않지만 사실상 같은 궤적인 에피소드 쌍.

    방법(결정적): 에피소드마다 state+action을 16개 시점으로 재표본하고
    차원별 데이터셋 표준편차로 나눈 서명을 만든다. 길이가 비슷한(±5%)
    쌍끼리 서명의 평균·최대 절댓값 차이를 재서 둘 다 허용오차 이하이면
    근접 중복으로 본다. A4의 정확 해시와 같은 쌍은 A4 담당이라 제외한다.
    허용오차는 provisional — 재업로드 시의 미세한 노이즈·반올림 차이는
    잡고, 같은 과제를 다시 수행한 별개 에피소드는 통과시키는 것이 목표다.
    """
    findings = []
    per = {}
    for e in ctx.reader.episodes:
        try:
            per[e["episode_index"]] = ctx.reader.episode_data(e)
        except Exception:
            continue
    if len(per) < 2:
        return findings
    eps_sorted = sorted(per)
    all_state = np.concatenate(
        [per[ep]["state"] for ep in eps_sorted]).astype(np.float64)
    all_action = np.concatenate(
        [per[ep]["action"] for ep in eps_sorted]).astype(np.float64)
    std_s = all_state.std(axis=0)
    std_s = np.where(std_s > 1e-9, std_s, 1.0)
    std_a = all_action.std(axis=0)
    std_a = np.where(std_a > 1e-9, std_a, 1.0)
    pts = int(TH["neardup_points"])
    sigs, lens, hashes = [], {}, {}
    for ep in eps_sorted:
        d = per[ep]
        n = len(d["state"])
        lens[ep] = n
        idx = (np.linspace(0, n - 1, pts).round().astype(int)
               if n > 0 else np.zeros(pts, dtype=int))
        sigs.append(np.concatenate([
            (d["state"][idx].astype(np.float64) / std_s).ravel(),
            (d["action"][idx].astype(np.float64) / std_a).ravel()]))
        hashes[ep] = _traj_hash(d)
    sig_mat = np.stack(sigs)
    for j, ep in enumerate(eps_sorted):
        if j == 0:
            continue
        cand = np.abs(sig_mat[:j] - sig_mat[j])
        mean_d = cand.mean(axis=1)
        max_d = cand.max(axis=1)
        ok = (mean_d <= TH["neardup_mean_tol"]) & (max_d <= TH["neardup_max_tol"])
        for i in range(j):
            ep0 = eps_sorted[i]
            if hashes[ep] == hashes[ep0]:
                ok[i] = False  # 정확 중복은 A4 담당
            elif abs(lens[ep] - lens[ep0]) > max(
                    2, TH["neardup_len_tol"] * max(lens[ep], lens[ep0])):
                ok[i] = False
        if ok.any():
            i = int(np.argmax(ok))  # 가장 이른 원본
            ep0 = eps_sorted[i]
            findings.append(_f(
                "A5", ep,
                f"near-duplicate trajectory of episode {ep0} "
                f"(mean |Δ| {mean_d[i]:.4f}σ, max {max_d[i]:.3f}σ — "
                "not an exact copy)",
                {"near_duplicate_of": ep0,
                 "mean_abs_diff_sigma": round(float(mean_d[i]), 5),
                 "max_abs_diff_sigma": round(float(max_d[i]), 4),
                 "method": f"{pts}-point resampled state+action, "
                           "per-dim σ-normalized"}))
    return findings


def idle_ratios(d):
    """에피소드 정지 지표 (A6와 리뷰 지표가 공유한다).

    정지 = 연속 프레임의 state+action 스텝 L2 합이 idle_step_eps 이하
    (사실상 완전히 같은 자세의 반복). 2프레임 미만이면 None.
    """
    n = len(d["state"])
    if n < 2:
        return None
    steps = (np.linalg.norm(np.diff(d["state"].astype(np.float64), axis=0),
                            axis=1)
             + np.linalg.norm(np.diff(d["action"].astype(np.float64),
                                     axis=0), axis=1))
    idle = steps <= TH["idle_step_eps"]
    lead = 0
    for x in idle:
        if x:
            lead += 1
        else:
            break
    longest = run = 0
    for x in idle:
        run = run + 1 if x else 0
        longest = max(longest, run)
    return {"idle_ratio": round(float(idle.mean()), 4),
            "leading_idle_ratio": round(lead / len(idle), 4),
            "longest_idle_run": int(longest),
            "idle_steps": int(idle.sum()),
            "steps_total": int(len(idle))}


def check_a6(ctx: Ctx):
    """에피소드 정지 비율: 녹화 시작 패딩이나 긴 멈춤이 있는 에피소드.

    A3(무동작 차원)는 차원이 통째로 죽은 경우만 본다. 여기서는 에피소드
    단위로 '자세 전체가 멈춘 프레임'의 비율을 본다 — 학습에 기여 없이
    길이만 차지하는 구간이다 (kinema idle-segments·rdq idle padding과
    같은 결함 계열). 임계값은 provisional.
    """
    findings = []
    for e in ctx.reader.episodes:
        ep = e["episode_index"]
        try:
            d = ctx.reader.episode_data(e)
        except Exception:
            continue
        r = idle_ratios(d)
        if r is None:
            continue
        if (r["idle_ratio"] >= TH["idle_ratio"]
                or r["leading_idle_ratio"] >= TH["idle_leading_ratio"]):
            ev = dict(r)
            ev["thresholds"] = {"idle_ratio": TH["idle_ratio"],
                                "leading_idle_ratio":
                                    TH["idle_leading_ratio"]}
            findings.append(_f(
                "A6", ep,
                f"idle frames {r['idle_ratio']:.0%} of episode "
                f"(leading idle {r['leading_idle_ratio']:.0%}, "
                f"longest run {r['longest_idle_run']} frames)", ev))
    return findings


def _feature_names(reader, key):
    """info.features[key].names를 문자열 리스트로 (v2.1 리스트/v3.0 dict)."""
    names = reader.info.get("features", {}).get(key, {}).get("names")
    if isinstance(names, dict):
        for v in names.values():
            if isinstance(v, list):
                return [str(x) for x in v]
    elif isinstance(names, list):
        return [str(x) for x in names]
    return None


def check_a7(ctx: Ctx):
    """리더·팔로워 캘리브레이션 드리프트: action−state의 체계적 오프셋.

    원격조작 데이터에서는 action이 리더(조작기) 자세, state가 팔로워
    (로봇) 자세인 경우가 많다. 둘의 중앙값 오프셋이 차원의 움직임
    표준편차 절반을 넘고 오프셋이 일정(사분위 범위가 표준편차 이하)하면
    캘리브레이션 어긋남의 신호로 본다 (kinema calibration-drift,
    LeRobot 이슈 #3758 계열). 차원 수나 차원 이름이 다르면 자세 대 자세
    비교가 성립하지 않아 적용하지 않는다. 임계값은 provisional.
    """
    reader = ctx.reader
    states, actions = [], []
    for e in reader.episodes:
        try:
            d = reader.episode_data(e)
        except Exception:
            continue
        states.append(d["state"].astype(np.float64))
        actions.append(d["action"].astype(np.float64))
    if not states:
        return []
    state = np.concatenate(states)
    action = np.concatenate(actions)
    if state.shape[1] != action.shape[1]:
        return []
    ns = _feature_names(reader, "observation.state")
    na = _feature_names(reader, "action")
    if ns is not None and na is not None and ns != na:
        return []
    diff = action - state
    offsets = np.median(diff, axis=0)
    stds = state.std(axis=0)
    iqrs = (np.quantile(diff, 0.75, axis=0)
            - np.quantile(diff, 0.25, axis=0))
    dims = []
    for j in range(state.shape[1]):
        if stds[j] <= 1e-9:
            continue
        ratio = abs(float(offsets[j])) / float(stds[j])
        if ratio > TH["calib_report_ratio"] and float(iqrs[j]) <= float(stds[j]):
            dims.append({"dim": j, "name": _dim_name(reader, "action", j),
                         "median_offset": round(float(offsets[j]), 4),
                         "state_std": round(float(stds[j]), 4),
                         "offset_ratio": round(ratio, 3),
                         "offset_iqr": round(float(iqrs[j]), 4)})
    if not dims:
        return []
    dims.sort(key=lambda d: -d["offset_ratio"])
    worst = dims[0]
    if worst["offset_ratio"] <= TH["calib_offset_ratio"]:
        return []
    return [_f("A7", None,
               f"systematic action-state offset: dim '{worst['name']}' "
               f"median offset {worst['median_offset']:+.3f} = "
               f"{worst['offset_ratio']:.2f} x state std "
               "(leader/follower calibration drift suspected)",
               {"dims": dims[:8],
                "max_offset_ratio": worst["offset_ratio"],
                "threshold": TH["calib_offset_ratio"],
                "method": "median(action - state) per dim over all frames "
                          "vs pooled state std; offset IQR <= state std "
                          "required (systematic, not noise)"})]


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
    "S4": check_s4, "S5": check_s5,
    "V1": check_v1, "V2": check_v2, "V3": check_v3,
    "A1": check_a1, "A2": check_a2, "A3": check_a3, "A4": check_a4,
    "A5": check_a5, "A6": check_a6, "A7": check_a7,
    "L1": check_l1, "L2": check_l2,
}
