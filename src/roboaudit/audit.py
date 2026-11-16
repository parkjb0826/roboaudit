"""감사 실행: 데이터셋 1개에 검사 12종을 돌려 결과 dict를 만든다.

보강(5단계):
- 검사 상태 분리: 검사마다 run_status(complete/partial/not_applicable/error)와
  실제 검사 범위(scope)를 기록한다. 디코딩 실패가 '정상'으로 집계되지 않으며,
  필수 검사가 불완전하면 incomplete_audit=True 로 종합에 명시한다.
- 처분 3단계: 에피소드를 exclude/review/keep으로 나눈다 (disposition.py).
- 감점 Top 3 요인과 재현 기록(run_manifest)을 결과에 포함한다.

0.3.0 추가 (전부 증거·진단 전용, 점수·등급·처분 불변):
- 타임스탬프 격자 진단(diagnostics.py)을 결과의 diagnostics 항목과
  성적표 상단 한 줄로 보고한다. 검사 12종에는 넣지 않는다.
- A2 finding에 게이트된 간격 비율과 state 추종 증거를 덧붙인다 (checks12.py).
"""
import hashlib
import shutil
import time
from pathlib import Path

from . import __version__
from .checks12 import CHECKS12, CHECK_NAMES, RULES_VERSION, SEVERITY, TH, Ctx
from .disposition import BORDERLINE_MARGIN, episode_dispositions, margin_ratio
from .scoring import score_findings

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
    if total == 0:
        return "not_applicable", "에피소드 없음"
    if data_bad:
        return "partial", f"데이터 읽음 {len(data_ok)}/{total} 에피소드"
    return "complete", f"데이터 {total}/{total} 에피소드"


def audit_dataset(root, sample_frames=None) -> dict:
    root = Path(root)
    t0 = time.time()
    ctx = Ctx(root, sample_frames=sample_frames)
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
    summary = {
        "dataset": root.name,
        "path": str(root),
        "format": reader.version,
        "video_key": reader.video_key,
        "video_keys": reader.video_keys,
        "robot_type": info.get("robot_type"),
        "total_episodes": len(all_eps),
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
        "dispositions": {str(ep): dispo.get(ep, "keep") for ep in all_eps},
    }
