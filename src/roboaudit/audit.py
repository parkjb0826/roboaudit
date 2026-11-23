"""감사 실행: 데이터셋 1개에 검사 17종을 돌려 결과 dict를 만든다.

보강(5단계):
- 검사 상태 분리: 검사마다 run_status(complete/partial/not_applicable/error)와
  실제 검사 범위(scope)를 기록한다. 디코딩 실패가 '정상'으로 집계되지 않으며,
  필수 검사가 불완전하면 incomplete_audit=True 로 종합에 명시한다.
- 처분 3단계: 에피소드를 exclude/review/keep으로 나눈다 (disposition.py).
- 감점 Top 3 요인과 재현 기록(run_manifest)을 결과에 포함한다.

0.3.0 추가 (전부 증거·진단 전용, 점수·등급·처분 불변):
- 타임스탬프 격자 진단(diagnostics.py)을 결과의 diagnostics 항목과
  성적표 상단 한 줄로 보고한다. 검사 항목에는 넣지 않는다.
- A2 finding에 게이트된 간격 비율과 state 추종 증거를 덧붙인다 (checks12.py).

0.3.1 변경 (전부 증거·진단 전용, 점수·등급·처분 불변):
- 공유 영상 구간의 프레임 단위 정확 슬라이스 (reader.py) — 0.3.0의
  밀리초 반올림 -t 구간 디코딩이 만들던 가짜 V3 발견을 제거한다.
- 타임스탬프 진단을 두 축(clock_provenance × interval_regularity)으로
  분리하고 frame_index 빈틈을 별도 신호로 보고한다 (diagnostics.py).
- A2 증거에 인덱스 빈틈(index_gap_at_jump)과 state-absent 미해결
  명시(state_note)를 덧붙인다 (checks12.py).

0.3.2 변경:
- 신규 검사 5종 (S4 기록 통계 드리프트, S5 라이선스·카드 기본값,
  A5 근접 중복, A6 에피소드 정지 비율, A7 캘리브레이션 드리프트).
  기존 12종의 검출 규칙·임계는 그대로다.
- 과제별 점수표(task_scores): 에피소드 단위 발견을 과제별로 묶은
  분해 점수. 데이터셋 단위 발견은 어느 과제에도 넣지 않고 따로 센다.
- 리뷰 단축목록(review_shortlist)과 에피소드 지표(episode_metrics),
  삭제 명령 묶음(delete_commands)을 결과에 포함한다 (metrics.py —
  명령은 출력만, 실행은 하지 않는다).
- 에피소드 표본 감사(max_episodes)와 repo_id 기록을 지원한다.
"""
import hashlib
import shutil
import time
from pathlib import Path

from . import __version__
from .checks12 import CHECKS12, CHECK_NAMES, RULES_VERSION, SEVERITY, TH, Ctx
from .disposition import BORDERLINE_MARGIN, episode_dispositions, margin_ratio
from .metrics import build_review_outputs, episode_metrics
from .scoring import DEDUCTION, grade_of, score_findings

VIDEO_CHECKS = {"V1", "V2", "V3"}

# 고지 문구 (추가 검토 2·5): 성적표와 result.json에 항상/조건부로 동봉한다.
NOTICE_SCOPE = ("범위 고지: RoboAudit는 데이터셋의 구조·통계적 이상을 검사하는 "
                "도구이며, 학습 성능이나 로봇의 안전성을 보증하지 않습니다.")
NOTICE_A2 = ("A2(급격한 점프) 해석 고지: A2 보류(review)는 측정값이 경계 근처라는 "
             "뜻이며, 이 검사만으로는 기록 결함과 운용 특성(프레임 드롭·빠른 동작 등)을 "
             "구분할 수 없습니다. 보류는 무해하다는 판정이 아닙니다.")
NOTICE_SAMPLE = ("표본 모드 고지: 표본 결과는 근사치입니다. 표본에서는 프레임 간격이 "
                 "벌어져 V1 정지 판정이 전수보다 엄격해질 수 있고 경계 구간의 정지를 "
                 "놓칠 수 있으므로, 최종 판정은 전수 재실행을 권장합니다.")
NOTICE_EPISODE_SAMPLE = ("에피소드 표본 고지: --max-episodes로 앞쪽 일부 에피소드만 "
                         "감사한 결과입니다. 점수·처분은 감사한 에피소드에 대해서만 "
                         "계산했고, 선언 총량과 대조하는 검사는 건너뛰었습니다.")


def _task_scores(reader, findings):
    """과제별 점수표 (0.3.2): 에피소드 단위 발견을 그 에피소드의 과제
    (첫 번째 지시문)별로 묶은 분해 점수. 데이터셋 단위 발견은 어느
    과제에도 속하지 않으므로 별도 감점 합계로만 돌려준다."""
    task_of_ep = {}
    for e in reader.episodes:
        tasks = [str(t) for t in e.get("tasks", []) if str(t).strip()]
        task_of_ep[e["episode_index"]] = tasks[0] if tasks else "(지시문 없음)"
    groups = {}
    for ep in sorted(task_of_ep):
        g = groups.setdefault(task_of_ep[ep],
                              {"task": task_of_ep[ep], "episodes": 0,
                               "findings": 0, "deduction": 0})
        g["episodes"] += 1
    dataset_level = 0
    for f in findings:
        if f["episode_index"] is None:
            dataset_level += DEDUCTION[f["severity"]]
            continue
        g = groups.get(task_of_ep.get(f["episode_index"]))
        if g is not None:
            g["findings"] += 1
            g["deduction"] += DEDUCTION[f["severity"]]
    out = []
    for t in sorted(groups):
        g = groups[t]
        g["score"] = max(0, 100 - g["deduction"])
        g["grade"] = grade_of(g["score"])
        out.append(g)
    return out, dataset_level


def input_fingerprint(root: Path) -> dict:
    """입력 지문: 전 파일 (상대경로, 크기, SHA-256) 목록의 SHA-256."""
    entries = []
    total_bytes = 0
    for p in sorted(root.rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            total_bytes += len(data)
            entries.append(f"{p.relative_to(root)}\0{len(data)}\0"
                           f"{hashlib.sha256(data).hexdigest()}")
    digest = hashlib.sha256("\n".join(entries).encode()).hexdigest()
    return {"algorithm": "sha256(file list: relpath, size, sha256)",
            "value": digest, "n_files": len(entries),
            "total_bytes": total_bytes}


def _check_status(code, ctx, errors, data_ok, data_bad):
    """검사 1개의 (run_status, scope) 산정."""
    reader = ctx.reader
    total = len(reader.episodes)
    if code in errors:
        return "error", f"검사 실행 오류: {errors[code]}"
    if code in VIDEO_CHECKS:
        if not reader.video_keys:
            return "not_applicable", "선언된 영상 피처 없음"
        dec = reader.decode_summary()
        parts, complete = [], True
        for key in reader.video_keys:
            d = dec.get(key, {"episodes_decoded": 0, "episodes_failed": [],
                              "episodes_missing_file": []})
            n_fail = len(d["episodes_failed"])
            n_miss = len(d["episodes_missing_file"])
            parts.append(f"{key}: 디코딩 {d['episodes_decoded']}/{total}"
                         f", 실패 {n_fail}, 파일없음 {n_miss}")
            if n_fail or n_miss:
                complete = False
        return ("complete" if complete else "partial"), "; ".join(parts)
    # 데이터 기반 검사
    if code == "S4":
        src = reader.recorded_stats()
        if src is None:
            return "not_applicable", ("기록 통계 없음 (stats.json·"
                                      "episodes_stats.jsonl·에피소드 메타 "
                                      "통계 열 모두 없음)")
        if getattr(reader, "episode_sampled", False) \
                and not src.get("per_episode"):
            return "not_applicable", ("에피소드 표본 감사 — 데이터셋 단위 "
                                      "기록 통계와 비교하지 않음")
    if code == "S5" and reader.dataset_card() is None:
        return "not_applicable", ("데이터셋 카드(README.md)가 로컬 복사본에 "
                                  "없음 — 라이선스 판단 보류")
    if total == 0:
        return "not_applicable", "에피소드 없음"
    if data_bad:
        return "partial", f"데이터 읽음 {len(data_ok)}/{total} 에피소드"
    return "complete", f"데이터 {total}/{total} 에피소드"


def audit_dataset(root, sample_frames=None, max_episodes=None,
                  repo_id=None) -> dict:
    root = Path(root)
    t0 = time.time()
    ctx = Ctx(root, sample_frames=sample_frames, max_episodes=max_episodes)
    reader = ctx.reader
    findings, errors = [], {}
    for code, fn in CHECKS12.items():
        try:
            findings.extend(fn(ctx))
        except Exception as exc:  # 검사 하나가 죽어도 전체는 계속
            errors[code] = f"{type(exc).__name__}: {exc}"
    findings.sort(key=lambda f: (f["check"],
                                 -1 if f["episode_index"] is None else f["episode_index"]))
    score, grade, per_check = score_findings(findings)

    # 처분 3단계 (findings는 그대로, 처분만 분리)
    for f in findings:
        m = margin_ratio(f)
        f["margin_ratio"] = None if m is None else round(min(m, 999.0), 3)
    dispo = episode_dispositions(findings)
    all_eps = [e["episode_index"] for e in reader.episodes]
    flagged = {}
    for f in findings:
        if f["episode_index"] is not None:
            flagged.setdefault(f["episode_index"], []).append(f["check"])
    clean_eps = [ep for ep in all_eps if ep not in flagged]
    excluded_eps = [ep for ep in all_eps if dispo.get(ep) == "exclude"]
    review_eps = [ep for ep in all_eps if dispo.get(ep) == "review"]
    full_dispo = {ep: dispo.get(ep, "keep") for ep in all_eps}

    # 0.3.2: 과제별 점수표 + 에피소드 지표·리뷰 단축목록 (정보 전용 —
    # 점수·처분을 바꾸지 않는다)
    task_scores, dataset_level_deduction = _task_scores(reader, findings)
    ep_metrics = episode_metrics(reader)
    shortlist, delete_cmds = build_review_outputs(
        reader, findings, full_dispo, ep_metrics, repo_id, root)

    # 검사 상태·범위
    data_ok, data_bad = reader.data_availability()
    check_table = []
    for code in CHECKS12:
        run_status, scope = _check_status(code, ctx, errors, data_ok, data_bad)
        check_table.append({
            "check": code,
            "name": CHECK_NAMES[code],
            "severity": SEVERITY[code],
            "findings": per_check.get(code, {}).get("findings", 0),
            "deduction": per_check.get(code, {}).get("deduction", 0),
            "status": "FAIL" if per_check.get(code, {}).get("findings", 0) else "PASS",
            "run_status": run_status,
            "scope": scope,
            "error": errors.get(code),
        })
    incomplete = any(c["run_status"] in ("partial", "error")
                     for c in check_table)

    # 감점 Top 3 요인
    total_deduction = sum(c["deduction"] for c in check_table)
    ranked = sorted((c for c in check_table if c["deduction"] > 0),
                    key=lambda c: (-c["deduction"], c["check"]))
    top_factors = [{
        "check": c["check"], "name": c["name"], "findings": c["findings"],
        "deduction": c["deduction"],
        "share_pct": round(100.0 * c["deduction"] / total_deduction, 1)
        if total_deduction else 0.0,
    } for c in ranked[:3]]

    info = reader.info
    # 고지: 범위 고지는 항상, A2·표본 고지는 해당할 때만.
    notices = [NOTICE_SCOPE]
    if any(f["check"] == "A2" for f in findings):
        notices.append(NOTICE_A2)
    if sample_frames:
        notices.append(NOTICE_SAMPLE)
    if getattr(reader, "episode_sampled", False):
        notices.append(NOTICE_EPISODE_SAMPLE)
    summary = {
        "dataset": root.name,
        "path": str(root),
        "repo_id": repo_id,
        "format": reader.version,
        "video_key": reader.video_key,
        "video_keys": reader.video_keys,
        "robot_type": info.get("robot_type"),
        "total_episodes": len(all_eps),
        "episodes_audited": len(all_eps),
        "max_episodes": max_episodes,
        "total_frames_meta": int(info.get("total_frames", 0)),
        "fps": info.get("fps"),
        "total_tasks": int(info.get("total_tasks", 0)),
        "incomplete_audit": incomplete,
        "sample_frames": sample_frames,
    }
    decode = reader.decode_summary()
    manifest = {
        "tool": {"name": "roboaudit", "version": __version__},
        "rules_version": RULES_VERSION,
        "thresholds": TH,
        "disposition": {"borderline_margin": BORDERLINE_MARGIN,
                        "note": f"margin_ratio >= {BORDERLINE_MARGIN} -> exclude, "
                                f"< {BORDERLINE_MARGIN} or info-only -> review"},
        "input_fingerprint": input_fingerprint(root),
        "video_decode": {
            "backends_available": {"opencv": True,
                                   "ffmpeg": shutil.which("ffmpeg")},
            "per_camera": decode,
        },
        "sample_frames": sample_frames,
        "max_episodes": max_episodes,
        "repo_id": repo_id,
        "audit_seconds": round(time.time() - t0, 1),
    }
    return {
        "summary": summary,
        "score": score,
        "grade": grade,
        "total_deduction": total_deduction,
        "incomplete_audit": incomplete,
        "notices": notices,
        "diagnostics": {"timestamp_grid": ctx.timestamp_grid()},
        "top_factors": top_factors,
        "task_scores": task_scores,
        "dataset_level_deduction": dataset_level_deduction,
        "episode_metrics": {str(ep): ep_metrics[ep]
                            for ep in sorted(ep_metrics)},
        "review_shortlist": shortlist,
        "delete_commands": delete_cmds,
        "checks": check_table,
        "findings": findings,
        "errors": errors,
        "manifest": manifest,
        "clean_episodes": clean_eps,
        "excluded_episodes": [
            {"episode_index": ep, "checks": sorted(set(flagged[ep]))}
            for ep in excluded_eps
        ],
        "review_episodes": [
            {"episode_index": ep, "checks": sorted(set(flagged[ep]))}
            for ep in review_eps
        ],
        "dispositions": {str(ep): full_dispo[ep] for ep in all_eps},
    }
