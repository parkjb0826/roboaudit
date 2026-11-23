"""데이터셋 진단 — 검사와 별개로, 점수·등급·처분에 영향을 주지 않는다.

타임스탬프 진단은 0.3.1부터 두 축으로 분리해 보고한다 (0.3.0은 단일 격자 판정):

1. clock_provenance — timestamp 열이 frame_index/fps 로 합성된 격자인지
   (synthetic_grid), 아니면 실제 촬영 시계로 볼 여지가 있는지
   (real_or_unverified). LeRobot 작성기는 실제 촬영 시각이 아니라
   frame_index/fps 를 timestamp로 기록하는 경우가 많고(sreetz 실데이터에서
   전 에피소드 확인), 격자 시계에서는 구간 간격 기반 추론(프레임 드롭 판정
   등)이 원리적으로 불가능하다. 이 축이 A2의 간격 비율 증거를 게이트한다.
2. interval_regularity — 연속 간격이 균일한지, 벌어진 지점이 있는지.

여기에 frame_index 자체의 빈틈(index gap)을 별도 신호로 보고한다. 인덱스
빈틈은 '기록 후 행 삭제'를 뜻하는 인덱스 유래 신호이며(캡처 시점의 레코더는
연속 인덱스를 쓴다), 시계 증거가 아니다. 그래서 격자 판정과 합치지 않고,
간격 비율 게이트를 열지도 않으며, 인덱스 유래 비율이 normal-interval로
표기되는 일도 없다. 근거: synthetic_drop_validation 변형 (b)에서 0.3.0
진단이 S3가 보는 벌어진 간격을 스스로도 세면서 '정보 없음'으로 보고한
자기모순이 드러났고, 외부 리뷰 3인의 공통 하한이 '두 축 분리 + 인덱스
빈틈은 출처를 밝힌 별도 증거'였다.

근거 데이터: exp/results/a2_interval_test/RESULTS.md (비율 15건 전부
1.000, 최대 편차 4.45e-7초), exp/results/synthetic_drop_validation/.
"""
import numpy as np

# 격자 판정 허용 오차(초). float32 반올림 오차(~1e-6초 수준)보다 충분히 크고,
# 한 프레임 간격(240fps에서도 4.2ms)보다 충분히 작다. 이 오차 이하의 편차는
# 프레임 드롭 신호(간격이 프레임 주기만큼 늘어남)를 담을 수 없다.
GRID_TOL_S = 1e-3

# 리포트에 싣는 인덱스 빈틈 위치 요약의 상한 (전량은 locations_truncated로 표시).
MAX_GAP_LOCATIONS = 20

MSG_GRID = ("Timestamps: synthetic grid (frame_index/fps) — "
            "interval-based reasoning not applicable")
MSG_INFORMATIVE = "Timestamps: informative (real capture timing)"
MSG_UNKNOWN = ("Timestamps: could not be assessed "
               "(fps missing or no readable episode data)")

INDEX_GAP_MEANING = ("frame_index gaps mean rows were removed after "
                     "recording — a capture-time recorder writes "
                     "contiguous indices")
INDEX_GAP_PROVENANCE = "index-derived, not a clock"


def _gap_locations(fi):
    """frame_index 배열에서 빈틈(step > 1)의 위치 목록과 집계를 낸다."""
    events = []
    missing_total = 0
    if len(fi) > 1:
        steps = np.diff(fi)
        for i in np.nonzero(steps > 1)[0]:
            step = int(steps[i])
            events.append({"after_frame_index": int(fi[i]),
                           "index_step": step,
                           "missing_rows": step - 1})
            missing_total += step - 1
    return events, missing_total


def _compose_message(clock_provenance, regularity, widened, deviating,
                     index_gaps):
    """두 축 + 인덱스 신호를 한 줄로 합친다. 자기모순이 생기지 않게,
    격자 시계여도 벌어진 간격과 인덱스 빈틈은 같은 문장에 함께 밝힌다."""
    if clock_provenance is None:
        return MSG_UNKNOWN
    parts = [MSG_GRID if clock_provenance == "synthetic_grid"
             else MSG_INFORMATIVE]
    if regularity == "widened_at_points":
        parts.append(f"{widened} timestamp intervals widened beyond 1/fps")
    elif regularity == "irregular":
        parts.append(f"{deviating} timestamp intervals deviate from 1/fps")
    if index_gaps["gap_events"]:
        parts.append(
            f"frame_index gaps: {index_gaps['gap_events']} gaps in "
            f"{index_gaps['episodes_with_gaps']} episodes, "
            f"{index_gaps['missing_frames']} rows missing "
            f"(index-derived signal: rows removed after recording)")
    return "; ".join(parts)


def timestamp_grid_diagnostic(reader) -> dict:
    """reader의 전 에피소드에 대해 타임스탬프 두 축 + 인덱스 빈틈을 진단한다.

    clock_provenance 판정: 에피소드별 시작 오프셋(timestamp[0] -
    frame_index[0]/fps)을 뺀 뒤 |timestamp - frame_index/fps| 의 데이터셋
    최대값이 GRID_TOL_S 이하면 synthetic_grid. 오프셋을 빼는 이유: 에피소드
    시작점의 상수 이동은 타이밍 정보가 아니므로 격자 판정에서 제외한다
    (격자는 '간격 구조'가 frame_index와 동형인지를 본다).
    """
    fps_raw = reader.info.get("fps")
    try:
        fps = float(fps_raw) if fps_raw else None
    except (TypeError, ValueError):
        fps = None
    out = {
        "is_grid": None,
        "clock_provenance": None,
        "interval_regularity": None,
        "fps": fps,
        "max_deviation_s": None,
        "informative": False,
        "episodes_checked": 0,
        "rows_checked": 0,
        "intervals_checked": 0,
        "median_interval_s": None,
        "intervals_deviating_gt_1ms": 0,
        "intervals_widened_gt_1ms": 0,
        "frame_index_gap_episodes": 0,
        "index_gaps": {
            "episodes_with_gaps": 0,
            "gap_events": 0,
            "missing_frames": 0,
            "locations": [],
            "locations_truncated": False,
            "meaning": INDEX_GAP_MEANING,
            "provenance": INDEX_GAP_PROVENANCE,
        },
        "message": MSG_UNKNOWN,
        "note": ("clock_provenance: synthetic_grid if max |timestamp - "
                 "frame_index/fps - episode offset| "
                 f"<= {GRID_TOL_S}s across all episodes (offsets are removed "
                 "per episode because a constant start shift carries no "
                 "timing information); interval_regularity is judged from "
                 "the timestamp intervals themselves. index_gaps are a "
                 "separate index-derived signal (rows removed after "
                 "recording): they neither change clock_provenance nor open "
                 "the interval-ratio gate, and no ratio is ever derived "
                 "from the index."),
    }
    if not fps or fps <= 0:
        return out
    max_dev = 0.0
    all_diffs = []
    gap_locations = []
    for e in reader.episodes:
        try:
            d = reader.episode_data(e)
        except Exception:
            continue
        ts = np.asarray(d["timestamp"], dtype=np.float64)
        fi = np.asarray(d["frame_index"], dtype=np.float64)
        if len(ts) == 0 or len(ts) != len(fi):
            continue
        out["episodes_checked"] += 1
        out["rows_checked"] += int(len(ts))
        offset = ts[0] - fi[0] / fps
        dev = np.abs(ts - fi / fps - offset)
        if len(dev):
            max_dev = max(max_dev, float(dev.max()))
        if len(fi) > 1 and not bool(np.all(np.diff(fi) == 1)):
            out["frame_index_gap_episodes"] += 1
        events, missing = _gap_locations(fi)
        if events:
            ig = out["index_gaps"]
            ig["episodes_with_gaps"] += 1
            ig["gap_events"] += len(events)
            ig["missing_frames"] += missing
            for ev in events:
                gap_locations.append({"episode_index": e["episode_index"],
                                      **ev})
        if len(ts) > 1:
            all_diffs.append(np.diff(ts))
    if out["episodes_checked"] == 0 or out["rows_checked"] == 0:
        return out
    out["max_deviation_s"] = round(max_dev, 9)
    widened = deviating = 0
    if all_diffs:
        diffs = np.concatenate(all_diffs)
        out["intervals_checked"] = int(len(diffs))
        out["median_interval_s"] = round(float(np.median(diffs)), 6)
        dev_mask = np.abs(diffs - 1.0 / fps) > GRID_TOL_S
        deviating = int(np.sum(dev_mask))
        widened = int(np.sum(diffs > 1.0 / fps + GRID_TOL_S))
        out["intervals_deviating_gt_1ms"] = deviating
        out["intervals_widened_gt_1ms"] = widened
    if deviating == 0:
        regularity = "uniform"
    elif widened == deviating:
        regularity = "widened_at_points"
    else:
        regularity = "irregular"
    out["interval_regularity"] = regularity
    ig = out["index_gaps"]
    ig["locations"] = gap_locations[:MAX_GAP_LOCATIONS]
    ig["locations_truncated"] = len(gap_locations) > MAX_GAP_LOCATIONS
    is_grid = max_dev <= GRID_TOL_S
    out["is_grid"] = bool(is_grid)
    out["clock_provenance"] = "synthetic_grid" if is_grid \
        else "real_or_unverified"
    out["informative"] = not is_grid
    out["message"] = _compose_message(out["clock_provenance"], regularity,
                                      widened, deviating, ig)
    return out
