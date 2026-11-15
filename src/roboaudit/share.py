"""동의 기반(opt-in) 익명 공유 묶음(share bundle) 생성.

목적: 사용자들이 자기 감사 결과의 **익명 요약만** 자발적으로 제출해,
검사별 발견 빈도·margin 분포·사람 판정(오탐 신고) 같은 사례 데이터가
쌓이게 하는 것. 이 사례가 처분 기준값(경계 1.5 등) 일반성 검증의
재료가 된다.

절대 원칙:
- 자동 전송 없음. 이 모듈은 파일만 만들 뿐, 네트워크로 아무것도 보내지
  않는다. 제출은 사용자가 파일을 직접 GitHub 이슈 등에 첨부하는 수동
  행동으로만 이뤄진다.
- 기본값 OFF: 감사 실행만으로는 bundle이 생기지 않는다.
  `roboaudit share <result.json>` 또는 감사 시 `--share-bundle`을
  명시했을 때만 생성된다.
- 화이트리스트 추출: result.json에서 아래 명시한 필드만 뽑는다.
  데이터셋 이름·경로·파일명·과제(task) 원문/해시·입력 지문·로봇 종류·
  카메라 키 이름·findings의 detail/evidence 원문은 **절대** 포함하지
  않는다. (detail에는 과제 원문이, evidence에는 측정 원값이 들어갈 수
  있기 때문이다.)
"""
import json
import statistics
from pathlib import Path

BUNDLE_TYPE = "roboaudit_share_bundle"
BUNDLE_VERSION = 1

# margin_ratio 히스토그램 버킷 경계. margin_ratio는 result.json에서
# 무한대가 999로 캡핑되어 저장되므로 마지막 버킷에 들어간다.
MARGIN_BUCKET_EDGES = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 10.0]
MARGIN_BUCKET_LABELS = ["0_to_0.5", "0.5_to_1.0", "1.0_to_1.5",
                        "1.5_to_2.0", "2.0_to_3.0", "3.0_to_10",
                        "10_or_more"]

ABOUT = {
    "what_this_is": (
        "An anonymised summary of one RoboAudit dataset audit, created "
        "only because the user explicitly asked for it (roboaudit share "
        "or --share-bundle). RoboAudit never sends anything anywhere: "
        "this file is written locally, and sharing it (for example by "
        "attaching it to a GitHub issue) is a separate manual step that "
        "is entirely the user's choice."),
    "contains": [
        "tool and rules versions",
        "dataset format (v2.1 / v3.0), episode count, total frame count, "
        "camera count, task count (counts only)",
        "score and grade",
        "per-check finding counts, severity counts, run-status counts",
        "per-check margin-ratio distribution (min / median / max and a "
        "histogram) - margins are ratios to thresholds, not raw data",
        "episode disposition totals (exclude / review / keep)",
        "whether sampling mode was used",
        "an empty adjudication template the user may fill in by hand",
    ],
    "does_not_contain": [
        "dataset name or any file/folder path (absolute or relative)",
        "file names of any kind",
        "task / instruction text (only how many distinct tasks exist), "
        "and no hashes of task text either",
        "video frames, images, or any raw sensor/action values",
        "finding detail text or evidence values",
        "camera/feature key names (only the camera count)",
        "robot type, user name, machine name, IP address, timestamps of "
        "the audit run, or the dataset input fingerprint",
    ],
    "why_cases_are_collected": (
        "Aggregated cases are used to validate RoboAudit's provisional "
        "disposition thresholds (e.g. the 1.5x borderline margin) across "
        "many real datasets, and to track which checks produce false "
        "positives in the field."),
}

ADJUDICATION_GUIDE = {
    "purpose": (
        "Optional, filled in by hand. For each flagged episode you "
        "personally inspected, record whether the tool was right. "
        "Human-adjudicated cases are what turn provisional thresholds "
        "into validated ones."),
    "verdict_values": {
        "agree": "I inspected this episode; the finding is a real defect.",
        "false_positive": "I inspected this episode; the finding is "
                          "wrong - the data is fine.",
        "unsure": "I looked, but cannot tell.",
        "missed_defect": "Add your own entry (check may be null) for an "
                         "episode the tool kept but that is actually "
                         "defective.",
    },
    "note": ("Episode indices are positions inside your own dataset "
             "only; they identify nothing outside it. Leave verdict "
             "null for episodes you did not inspect."),
}


def _margin_stats(values):
    """margin_ratio 목록 -> {count, min, median, max, histogram}."""
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None,
                "histogram": {label: 0 for label in MARGIN_BUCKET_LABELS}}
    hist = {label: 0 for label in MARGIN_BUCKET_LABELS}
    for v in values:
        for i, label in enumerate(MARGIN_BUCKET_LABELS):
            lo = MARGIN_BUCKET_EDGES[i]
            hi = (MARGIN_BUCKET_EDGES[i + 1]
                  if i + 1 < len(MARGIN_BUCKET_EDGES) else float("inf"))
            if lo <= v < hi or (i == len(MARGIN_BUCKET_LABELS) - 1
                                and v >= lo):
                hist[label] += 1
                break
    return {"count": len(values),
            "min": round(min(values), 3),
            "median": round(statistics.median(values), 3),
            "max": round(max(values), 3),
            "histogram": hist}


def build_bundle(result: dict) -> dict:
    """result.json dict -> 익명 공유 묶음 dict (화이트리스트 추출만)."""
    summary = result.get("summary", {})
    manifest = result.get("manifest", {})
    findings = result.get("findings", [])

    # 검사별 집계: checks 표(건수·실행 상태)와 findings(심각도·margin)를 결합
    margins_by_check = {}
    severity_by_check = {}
    for f in findings:
        code = f.get("check")
        sev = f.get("severity")
        if sev:
            severity_by_check.setdefault(code, {})
            severity_by_check[code][sev] = \
                severity_by_check[code].get(sev, 0) + 1
        m = f.get("margin_ratio")
        if m is not None:
            margins_by_check.setdefault(code, []).append(float(m))
    checks_out = []
    run_status_counts = {}
    for c in result.get("checks", []):
        code = c.get("check")
        rs = c.get("run_status")
        if rs:
            run_status_counts[rs] = run_status_counts.get(rs, 0) + 1
        checks_out.append({
            "check": code,
            "findings": c.get("findings", 0),
            "severity_counts": severity_by_check.get(code, {}),
            "run_status": rs,
            "margins": _margin_stats(margins_by_check.get(code, [])),
        })

    # 처분 집계 (에피소드 단위)
    disp_counts = {"exclude": 0, "review": 0, "keep": 0}
    for d in result.get("dispositions", {}).values():
        if d in disp_counts:
            disp_counts[d] += 1

    # 오탐·판정 신고 템플릿: 에피소드 단위 finding마다 빈 항목 1개
    dispositions = result.get("dispositions", {})
    adjudications = []
    for f in findings:
        ep = f.get("episode_index")
        if ep is None:
            continue
        adjudications.append({
            "check": f.get("check"),
            "episode_index": ep,
            "episode_disposition": dispositions.get(str(ep)),
            "verdict": None,
            "note": "",
        })

    video_keys = summary.get("video_keys") or []
    camera_count = len(video_keys) if video_keys else (
        1 if summary.get("video_key") else 0)
    sample_frames = summary.get("sample_frames")

    return {
        "bundle_type": BUNDLE_TYPE,
        "bundle_version": BUNDLE_VERSION,
        "about": ABOUT,
        "tool": {
            "name": "roboaudit",
            "version": manifest.get("tool", {}).get("version"),
            "rules_version": manifest.get("rules_version"),
        },
        "dataset_summary": {
            "format": summary.get("format"),
            "total_episodes": summary.get("total_episodes"),
            "total_frames": summary.get("total_frames_meta"),
            "camera_count": camera_count,
            "task_count": summary.get("total_tasks"),
        },
        "result_summary": {
            "score": result.get("score"),
            "grade": result.get("grade"),
            "total_deduction": result.get("total_deduction"),
            "findings_total": len(findings),
            "incomplete_audit": bool(result.get("incomplete_audit")),
            "sample_mode": bool(sample_frames),
            "sample_frames_per_episode": sample_frames,
            "dispositions": disp_counts,
            "run_status_counts": run_status_counts,
        },
        "checks": checks_out,
        "adjudication_guide": ADJUDICATION_GUIDE,
        "adjudications": adjudications,
    }


def bundle_from_result_file(result_path) -> dict:
    """result.json 파일을 읽어 bundle dict를 만든다."""
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    return build_bundle(result)


def write_bundle(result: dict, out_path) -> Path:
    """result dict -> share_bundle.json 파일. 경로 반환."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle(result)
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    return out
