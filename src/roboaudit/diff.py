"""감사 결과 diff (0.3.2, 연구 보고서 #8).

`roboaudit diff old.json new.json` — 두 result.json을 비교해 점수·등급,
검사별 발견 수, 생긴/사라진 발견, 에피소드 처분 변화를 보여준다.
재감사 때 "뭐가 좋아졌고 뭐가 새로 생겼나"를 눈으로 대조하지 않기
위한 도구다. 비교는 결정적이다: 발견의 동일성은 (검사, 에피소드,
detail) 세 값으로 판단한다.
"""
from collections import Counter


def _finding_key(f):
    return (f["check"], f["episode_index"], f["detail"])


def compare_results(old, new):
    """두 감사 결과 dict의 구조화 diff."""
    old_f = Counter(_finding_key(f) for f in old.get("findings", []))
    new_f = Counter(_finding_key(f) for f in new.get("findings", []))
    added = [{"check": k[0], "episode_index": k[1], "detail": k[2],
              "count": c} for k, c in sorted((new_f - old_f).items())]
    removed = [{"check": k[0], "episode_index": k[1], "detail": k[2],
                "count": c} for k, c in sorted((old_f - new_f).items())]
    checks = {}
    for c in old.get("checks", []) + new.get("checks", []):
        checks.setdefault(c["check"], {"old_findings": 0, "new_findings": 0,
                                       "old_deduction": 0,
                                       "new_deduction": 0})
    for c in old.get("checks", []):
        checks[c["check"]]["old_findings"] = c["findings"]
        checks[c["check"]]["old_deduction"] = c["deduction"]
    for c in new.get("checks", []):
        checks[c["check"]]["new_findings"] = c["findings"]
        checks[c["check"]]["new_deduction"] = c["deduction"]
    old_disp = old.get("dispositions", {})
    new_disp = new.get("dispositions", {})
    disp_changes = []
    for ep in sorted(set(old_disp) | set(new_disp), key=lambda x: int(x)):
        o, n = old_disp.get(ep, "(없음)"), new_disp.get(ep, "(없음)")
        if o != n:
            disp_changes.append({"episode_index": int(ep),
                                 "old": o, "new": n})
    return {
        "old": {"dataset": old.get("summary", {}).get("dataset"),
                "score": old.get("score"), "grade": old.get("grade"),
                "version": old.get("manifest", {}).get("tool", {})
                .get("version"),
                "rules_version": old.get("manifest", {}).get("rules_version")},
        "new": {"dataset": new.get("summary", {}).get("dataset"),
                "score": new.get("score"), "grade": new.get("grade"),
                "version": new.get("manifest", {}).get("tool", {})
                .get("version"),
                "rules_version": new.get("manifest", {}).get("rules_version")},
        "score_delta": (new.get("score", 0) - old.get("score", 0)),
        "checks": checks,
        "findings_added": added,
        "findings_removed": removed,
        "disposition_changes": disp_changes,
        "clean_old": len(old.get("clean_episodes", [])),
        "clean_new": len(new.get("clean_episodes", [])),
    }


def format_diff(cmp):
    """사람이 읽는 텍스트 요약."""
    o, n = cmp["old"], cmp["new"]
    lines = [
        f"RoboAudit diff — {o['dataset']} (v{o['version']}, "
        f"{o['rules_version']}) → {n['dataset']} (v{n['version']}, "
        f"{n['rules_version']})",
        f"점수: {o['score']}/{o['grade']} → {n['score']}/{n['grade']} "
        f"({cmp['score_delta']:+d})",
        f"깨끗한 에피소드: {cmp['clean_old']} → {cmp['clean_new']}",
        "",
        "검사별 발견 (이전 → 이후):",
    ]
    for code in sorted(cmp["checks"]):
        c = cmp["checks"][code]
        if c["old_findings"] != c["new_findings"] or \
                c["old_deduction"] != c["new_deduction"]:
            lines.append(f"  {code}: {c['old_findings']}건/-{c['old_deduction']}점"
                         f" → {c['new_findings']}건/-{c['new_deduction']}점")
    if all(c["old_findings"] == c["new_findings"]
           for c in cmp["checks"].values()):
        lines.append("  (변화 없음)")
    lines.append("")
    lines.append(f"새로 생긴 발견: {sum(a['count'] for a in cmp['findings_added'])}건")
    for a in cmp["findings_added"][:20]:
        ep = "전체" if a["episode_index"] is None else a["episode_index"]
        lines.append(f"  + [{a['check']}] ep {ep}: {a['detail']}")
    if len(cmp["findings_added"]) > 20:
        lines.append(f"  … 외 {len(cmp['findings_added']) - 20}건")
    lines.append(f"사라진 발견: {sum(a['count'] for a in cmp['findings_removed'])}건")
    for a in cmp["findings_removed"][:20]:
        ep = "전체" if a["episode_index"] is None else a["episode_index"]
        lines.append(f"  - [{a['check']}] ep {ep}: {a['detail']}")
    if len(cmp["findings_removed"]) > 20:
        lines.append(f"  … 외 {len(cmp['findings_removed']) - 20}건")
    lines.append("")
    lines.append(f"처분이 바뀐 에피소드: {len(cmp['disposition_changes'])}개")
    for ch in cmp["disposition_changes"][:20]:
        lines.append(f"  ep {ch['episode_index']}: {ch['old']} → {ch['new']}")
    if len(cmp["disposition_changes"]) > 20:
        lines.append(f"  … 외 {len(cmp['disposition_changes']) - 20}개")
    return "\n".join(lines)
