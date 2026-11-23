"""에피소드 지표·리뷰 단축목록·편집 명령 (0.3.2, 연구 보고서 #2·#4).

LeRobot 이슈 #3760의 요구 — "200개를 다 보는 것 → 이 8개만 보기" — 에
대한 RoboAudit의 답이다. 검사가 아니라 정보다: 점수·처분을 바꾸지 않고,
review 에피소드를 결정적 지표로 순위 매겨 '먼저 볼 목록'을 만들고,
공식 비주얼라이저 딥링크(repo_id를 아는 경우만)와 복사해서 쓰는
`lerobot-edit-dataset` 삭제 명령을 함께 출력한다.

원칙: RoboAudit는 편집 명령을 **실행하지 않는다**. 출력까지만 하고,
실행 여부와 실행 자체는 사용자 몫이다 (원본 읽기 전용 원칙).
"""
import numpy as np

from .checks12 import idle_ratios

VISUALIZER_BASE = "https://huggingface.co/spaces/lerobot/visualize_dataset"


def visualizer_url(repo_id, episode_index):
    """공식 비주얼라이저 에피소드 딥링크. repo_id를 모르면 만들지 않는다."""
    if not repo_id:
        return None
    return f"{VISUALIZER_BASE}?path=/{repo_id}/episode_{episode_index}"


def delete_command(repo_id, root, episode_indices):
    """`lerobot-edit-dataset` 삭제 명령 (출력 전용 — 실행하지 않는다).

    문법은 LeRobot 공식 문서(Using Dataset Tools)의 delete_episodes
    예시와 같다. repo_id를 모르는 로컬 폴더는 폴더명을 repo_id 자리에,
    --root로 실제 경로를 함께 적는다.
    """
    idx = "[" + ", ".join(str(int(i)) for i in episode_indices) + "]"
    if repo_id:
        head = f"lerobot-edit-dataset --repo_id {repo_id}"
    else:
        from pathlib import Path
        head = (f"lerobot-edit-dataset --repo_id {Path(root).name} "
                f"--root {root}")
    return (f"{head} --operation.type delete_episodes "
            f"--operation.episode_indices \"{idx}\"")


def episode_metrics(reader):
    """에피소드별 결정적 지표 (단축목록·지표표용, 점수와 무관).

    jerk_p95: state 3차 차분 L2의 95백분위 (움직임의 거칠기)
    max_step: state 최대 프레임간 스텝 L2
    idle_ratio / leading_idle_ratio: A6와 같은 정의 (checks12.idle_ratios)
    final_pose_distance: 최종 state 자세가 데이터셋 중앙값 최종 자세에서
    떨어진 거리 (차원별 표준편차로 나눈 유클리드 거리, σ 단위)
    """
    per = {}
    for e in reader.episodes:
        try:
            per[e["episode_index"]] = reader.episode_data(e)
        except Exception:
            continue
    finals, stds = {}, None
    if per:
        all_state = np.concatenate(
            [per[ep]["state"] for ep in sorted(per)]).astype(np.float64)
        stds = all_state.std(axis=0)
        stds = np.where(stds > 1e-9, stds, 1.0)
        for ep, d in per.items():
            if len(d["state"]):
                finals[ep] = d["state"][-1].astype(np.float64)
    med_final = None
    if finals:
        med_final = np.median(np.stack([finals[ep] for ep in sorted(finals)]),
                              axis=0)
    out = {}
    for ep in sorted(per):
        d = per[ep]
        state = d["state"].astype(np.float64)
        m = {"length": int(len(state)), "jerk_p95": None, "max_step": None,
             "idle_ratio": None, "leading_idle_ratio": None,
             "final_pose_distance": None}
        if len(state) >= 2:
            steps = np.linalg.norm(np.diff(state, axis=0), axis=1)
            m["max_step"] = round(float(steps.max()), 4)
        if len(state) >= 4:
            jerk = np.linalg.norm(np.diff(state, n=3, axis=0), axis=1)
            if len(jerk):
                m["jerk_p95"] = round(float(np.quantile(jerk, 0.95)), 4)
        r = idle_ratios(d)
        if r is not None:
            m["idle_ratio"] = r["idle_ratio"]
            m["leading_idle_ratio"] = r["leading_idle_ratio"]
        if ep in finals and med_final is not None:
            dist = np.linalg.norm((finals[ep] - med_final) / stds)
            m["final_pose_distance"] = round(float(dist), 3)
        out[ep] = m
    return out


_METRIC_KEYS = ("jerk_p95", "max_step", "idle_ratio", "final_pose_distance")


def _robust_outlier(values_by_ep):
    """지표별 중앙값·IQR 기준 이상치 점수: max |x - 중앙값| / IQR."""
    scores = {ep: 0.0 for ep in values_by_ep}
    for key in _METRIC_KEYS:
        vals = {ep: m[key] for ep, m in values_by_ep.items()
                if m.get(key) is not None}
        if len(vals) < 4:
            continue
        arr = np.array(list(vals.values()), dtype=np.float64)
        med = float(np.median(arr))
        iqr = float(np.quantile(arr, 0.75) - np.quantile(arr, 0.25))
        scale = iqr if iqr > 1e-12 else (float(arr.std()) or 1.0)
        for ep, v in vals.items():
            scores[ep] = max(scores[ep], abs(v - med) / scale)
    return scores


def build_review_outputs(reader, findings, dispositions, metrics,
                         repo_id, root, top_n=10):
    """(review_shortlist, delete_commands) 산출.

    단축목록: 처분이 review인 에피소드를 (이상치 점수 내림차순, 발견 수
    내림차순, 인덱스 오름차순)으로 순위 매긴 상위 top_n개. 각 항목에
    지표·걸린 검사·딥링크(repo_id가 있을 때만)·단일 에피소드 삭제 명령을
    싣는다. 삭제 명령 묶음은 exclude 에피소드 전체에 대한 것이다.
    """
    checks_by_ep = {}
    for f in findings:
        if f["episode_index"] is not None:
            checks_by_ep.setdefault(f["episode_index"], set()).add(f["check"])
    outliers = _robust_outlier(metrics)
    review_eps = [ep for ep in sorted(dispositions)
                  if dispositions[ep] == "review"]
    ranked = sorted(
        review_eps,
        key=lambda ep: (-outliers.get(ep, 0.0),
                        -len(checks_by_ep.get(ep, ())), ep))
    shortlist = []
    for rank, ep in enumerate(ranked[:top_n], start=1):
        shortlist.append({
            "rank": rank,
            "episode_index": ep,
            "checks": sorted(checks_by_ep.get(ep, ())),
            "outlier_score": round(outliers.get(ep, 0.0), 3),
            "metrics": metrics.get(ep),
            "visualizer_url": visualizer_url(repo_id, ep),
            "delete_command": delete_command(repo_id, root, [ep]),
        })
    excluded_eps = [ep for ep in sorted(dispositions)
                    if dispositions[ep] == "exclude"]
    commands = {
        "excluded_episodes": excluded_eps,
        "excluded_command": (delete_command(repo_id, root, excluded_eps)
                             if excluded_eps else None),
        "note": "RoboAudit는 이 명령을 실행하지 않습니다. 비주얼라이저로 "
                "확인한 뒤, 지울 에피소드만 골라 직접 실행하세요. "
                "(lerobot-edit-dataset은 원본을 고치는 도구입니다)",
    }
    return shortlist, commands
