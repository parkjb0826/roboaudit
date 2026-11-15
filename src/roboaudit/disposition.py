"""에피소드 처분 3단계: exclude(제외) / review(보류) / keep(유지).

findings(검출) 자체는 바꾸지 않고, 처분만 나눈다. 원칙:
- 명확한 위반만 제외한다.
- 측정 강도가 임계값 경계 근처이거나 참고(info) 수준 발견만 있으면 보류.
- 보류 에피소드는 review_index.json으로 따로 나가고, 사람이 최종 판단한다.

경계 판정: 검사별 margin_ratio = (측정된 위반 강도) / (임계값).
margin_ratio >= BORDERLINE_MARGIN(1.5) 이면 명확, 미만이면 경계로 본다.
검사별 강도 정의는 전부 evidence 기반이며 아래 _margin_* 에 명시한다.
margin을 계산할 수 없는 finding은 심각도 기준: info→보류,
warning/critical→제외 (구조적 위반은 측정 경계가 없는 명확한 위반으로 본다:
파일 없음, NaN, 시간 역전, 지시문 누락, 무동작 차원 등).
"""
from .checks12 import TH

BORDERLINE_MARGIN = 1.5
# A1 전용: 대역 폭 대비 초과 거리가 이 비율 이하면 경계 (4단계 표본 판정에서
# aloha 잔여 건이 '대역 경계 10~20% 초과'로 기록된 데 근거한 일반 기준)
A1_BORDERLINE_EXCEED = 0.25


def _margin_v1(f):
    ev = f.get("evidence", {})
    if "mean_brightness" in ev:  # 검은 화면: 밝기가 낮을수록 강한 위반
        b = ev["mean_brightness"]
        return float("inf") if b <= 0 else TH["black_brightness"] / b
    if "identical_ratio" in ev:  # 정지 화면
        r = ev["identical_ratio"]
        if r >= 0.99:  # 사실상 완전 정지 — 경계로 보지 않는다
            return 3.0
        return r / TH["static_ratio"]
    return None


def _margin_v2(f):
    ev = f.get("evidence", {})
    if "median_diff" in ev and ev.get("dataset_median_diff"):  # 흔들림(중앙값)
        return (ev["median_diff"] / ev["dataset_median_diff"]) / TH["shake_ratio"]
    if "max_diff" in ev:  # 흔들림(단일 글리치 가드)
        return ev["max_diff"] / TH["shake_single_abs"]
    if "lap_median" in ev and ev.get("dataset_lap_median"):  # 흐림
        denom = TH["blur_ratio"] * ev["dataset_lap_median"]
        return float("inf") if ev["lap_median"] <= 0 else denom / ev["lap_median"]
    return None


def _margin_v3(f):
    ev = f.get("evidence", {})
    if "video_frames" in ev:  # 프레임 수 != 메타 길이: 정확한 불일치
        return 3.0
    if "ratio" in ev:  # 길이 분포 이탈
        r = ev["ratio"]
        return max(r, 1.0 / r) / TH["len_ratio"] if r else None
    return None


def _margin_a1(f):
    """대역 폭 대비 초과 거리 비율 / A1_BORDERLINE_EXCEED."""
    ev = f.get("evidence", {})
    cols = ev.get("columns", {})
    worst = 0.0
    for c in cols.values():
        lo, hi = c.get("band", [0, 0])
        width = hi - lo
        if width <= 0:
            continue
        beyond = max(lo - c.get("observed_min", lo),
                     c.get("observed_max", hi) - hi, 0.0)
        worst = max(worst, beyond / width)
    if not cols:
        return None
    return worst / A1_BORDERLINE_EXCEED


def _margin_a2(f):
    ev = f.get("evidence", {})
    if "max_step" in ev and ev.get("dataset_floor"):
        return ev["max_step"] / ev["dataset_floor"]
    return None


_MARGIN = {"V1": _margin_v1, "V2": _margin_v2, "V3": _margin_v3,
           "A1": _margin_a1, "A2": _margin_a2}


def margin_ratio(f):
    """finding의 위반 강도 / 임계값. 계산 불가면 None."""
    fn = _MARGIN.get(f["check"])
    if fn is None:
        return None
    try:
        return fn(f)
    except Exception:
        return None


def finding_disposition(f) -> str:
    """finding 1건의 처분: 'exclude' 또는 'review'."""
    if f["severity"] == "info":
        return "review"
    m = margin_ratio(f)
    if m is not None:
        return "exclude" if m >= BORDERLINE_MARGIN else "review"
    return "exclude"


def episode_dispositions(findings):
    """에피소드별 처분 dict. exclude > review > keep 우선순위."""
    out = {}
    for f in findings:
        ep = f["episode_index"]
        if ep is None:
            continue
        d = finding_disposition(f)
        cur = out.get(ep)
        if cur == "exclude":
            continue
        if d == "exclude" or cur is None:
            out[ep] = d
        elif cur != "review":
            out[ep] = d
    return out
