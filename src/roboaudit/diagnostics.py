"""데이터셋 진단 — 검사 12종과 별개로, 점수·등급·처분에 영향을 주지 않는다.

타임스탬프 격자 진단: timestamp 열이 frame_index/fps 로 합성된 격자인지 판정한다.
LeRobot 작성기는 실제 촬영 시각이 아니라 frame_index/fps 를 timestamp로 기록하는
경우가 많고(sreetz 실데이터에서 전 에피소드 확인), 그런 데이터에서는 구간 간격
기반 추론(프레임 드롭 판정 등)이 원리적으로 불가능하다. 이 진단이 A2의 간격
비율 증거를 게이트한다. 근거: exp/results/a2_interval_test/RESULTS.md (비율
15건 전부 1.000, 최대 편차 4.45e-7초), 후속 교차 리뷰에서 '파일로 구분 불가'는
과장이라는 지적과 함께 격자 진단이 최우선 후속으로 합의됨.
"""
import numpy as np

# 격자 판정 허용 오차(초). float32 반올림 오차(~1e-6초 수준)보다 충분히 크고,
# 한 프레임 간격(240fps에서도 4.2ms)보다 충분히 작다. 이 오차 이하의 편차는
# 프레임 드롭 신호(간격이 프레임 주기만큼 늘어남)를 담을 수 없다.
GRID_TOL_S = 1e-3

MSG_GRID = ("Timestamps: synthetic grid (frame_index/fps) — "
            "interval-based reasoning not applicable")
MSG_INFORMATIVE = "Timestamps: informative (real capture timing)"
MSG_UNKNOWN = ("Timestamps: could not be assessed "
               "(fps missing or no readable episode data)")


def timestamp_grid_diagnostic(reader) -> dict:
    """reader의 전 에피소드에 대해 timestamp 격자 여부를 진단한다.

    판정: 에피소드별 시작 오프셋(timestamp[0] - frame_index[0]/fps)을 뺀 뒤
    |timestamp - frame_index/fps| 의 데이터셋 최대값이 GRID_TOL_S 이하면 격자.
    오프셋을 빼는 이유: 에피소드 시작점의 상수 이동은 타이밍 정보가 아니므로
    격자 판정에서 제외한다 (격자는 '간격 구조'가 frame_index와 동형인지를 본다).
    """
    fps_raw = reader.info.get("fps")
    try:
        fps = float(fps_raw) if fps_raw else None
    except (TypeError, ValueError):
        fps = None
    out = {
        "is_grid": None,
        "fps": fps,
        "max_deviation_s": None,
        "informative": False,
        "episodes_checked": 0,
        "rows_checked": 0,
        "intervals_checked": 0,
        "median_interval_s": None,
        "intervals_deviating_gt_1ms": 0,
        "frame_index_gap_episodes": 0,
        "message": MSG_UNKNOWN,
        "note": ("grid if max |timestamp - frame_index/fps - episode offset| "
                 f"<= {GRID_TOL_S}s across all episodes; offsets are removed "
                 "per episode because a constant start shift carries no "
                 "timing information"),
    }
    if not fps or fps <= 0:
        return out
    max_dev = 0.0
    all_diffs = []
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
        if len(ts) > 1:
            all_diffs.append(np.diff(ts))
    if out["episodes_checked"] == 0 or out["rows_checked"] == 0:
        return out
    out["max_deviation_s"] = round(max_dev, 9)
    if all_diffs:
        diffs = np.concatenate(all_diffs)
        out["intervals_checked"] = int(len(diffs))
        out["median_interval_s"] = round(float(np.median(diffs)), 6)
        out["intervals_deviating_gt_1ms"] = int(
            np.sum(np.abs(diffs - 1.0 / fps) > GRID_TOL_S))
    is_grid = max_dev <= GRID_TOL_S
    out["is_grid"] = bool(is_grid)
    out["informative"] = not is_grid
    out["message"] = MSG_GRID if is_grid else MSG_INFORMATIVE
    return out
