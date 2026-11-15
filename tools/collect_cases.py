#!/usr/bin/env python3
"""RoboAudit 사례 집계기 (운영자용).

동의 기반으로 제출된 share bundle 파일들이 모인 폴더를 읽어 사례
요약표를 만든다. 서버 없이 GitHub 이슈에 첨부된 bundle들을 모아 이
스크립트에 넣으면, 검사별 발견 빈도·margin 분포·사람 판정(오탐 신고)
집계가 나온다 — 처분 기준값(경계 1.5 등) 일반성 검증의 재료.

사용법:
  python tools/collect_cases.py <bundles_dir> [--out <out_dir>]

출력 (out_dir, 기본 bundles_dir):
  cases_summary.json  전체 집계
  cases_summary.csv   검사별 집계 (사례 수·발견 총건수·margin 히스토그램)

bundle이 아닌 JSON 파일은 경고만 남기고 건너뛴다.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

BUNDLE_TYPE = "roboaudit_share_bundle"
MARGIN_LABELS = ["0_to_0.5", "0.5_to_1.0", "1.0_to_1.5", "1.5_to_2.0",
                 "2.0_to_3.0", "3.0_to_10", "10_or_more"]


def load_bundles(folder: Path):
    bundles, skipped = [], []
    for p in sorted(folder.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append((p.name, f"JSON 파싱 실패: {exc}"))
            continue
        if d.get("bundle_type") != BUNDLE_TYPE:
            skipped.append((p.name, "share bundle이 아님"))
            continue
        bundles.append((p.name, d))
    return bundles, skipped


def aggregate(bundles):
    n = len(bundles)
    formats = Counter()
    grades = Counter()
    scores = []
    episodes_total = 0
    incomplete = 0
    sample_mode = 0
    disp_total = Counter()
    run_status_total = Counter()
    per_check = {}
    adjud = Counter()          # (check, verdict) -> 건수
    adjud_by_check = {}
    rules_versions = Counter()
    tool_versions = Counter()

    for _name, b in bundles:
        ds = b.get("dataset_summary", {})
        rs = b.get("result_summary", {})
        formats[ds.get("format")] += 1
        grades[rs.get("grade")] += 1
        if isinstance(rs.get("score"), (int, float)):
            scores.append(rs["score"])
        episodes_total += ds.get("total_episodes") or 0
        incomplete += 1 if rs.get("incomplete_audit") else 0
        sample_mode += 1 if rs.get("sample_mode") else 0
        disp_total.update(rs.get("dispositions", {}))
        run_status_total.update(rs.get("run_status_counts", {}))
        tool_versions[b.get("tool", {}).get("version")] += 1
        rules_versions[b.get("tool", {}).get("rules_version")] += 1
        for c in b.get("checks", []):
            code = c.get("check")
            slot = per_check.setdefault(code, {
                "cases": 0, "cases_with_findings": 0, "findings_total": 0,
                "severity_counts": Counter(),
                "margin_histogram": Counter(),
                "margin_count": 0,
            })
            slot["cases"] += 1
            f = c.get("findings", 0)
            slot["findings_total"] += f
            if f:
                slot["cases_with_findings"] += 1
            slot["severity_counts"].update(c.get("severity_counts", {}))
            m = c.get("margins", {})
            slot["margin_histogram"].update(m.get("histogram", {}))
            slot["margin_count"] += m.get("count", 0)
        for a in b.get("adjudications", []):
            v = a.get("verdict")
            if v:
                adjud[(a.get("check"), v)] += 1
                adjud_by_check.setdefault(a.get("check"), Counter())[v] += 1

    per_check_out = {}
    for code, s in sorted(per_check.items()):
        per_check_out[code] = {
            "cases": s["cases"],
            "cases_with_findings": s["cases_with_findings"],
            "findings_total": s["findings_total"],
            "severity_counts": dict(s["severity_counts"]),
            "margin_count": s["margin_count"],
            "margin_histogram": {label: s["margin_histogram"].get(label, 0)
                                 for label in MARGIN_LABELS},
        }
    return {
        "cases": n,
        "tool_versions": dict(tool_versions),
        "rules_versions": dict(rules_versions),
        "format_distribution": dict(formats),
        "grade_distribution": dict(grades),
        "score_stats": {
            "min": min(scores) if scores else None,
            "median": statistics.median(scores) if scores else None,
            "max": max(scores) if scores else None,
        },
        "episodes_total": episodes_total,
        "incomplete_audits": incomplete,
        "sample_mode_cases": sample_mode,
        "dispositions_total": dict(disp_total),
        "run_status_total": dict(run_status_total),
        "per_check": per_check_out,
        "adjudications": {
            "by_check_verdict": {f"{k[0]}:{k[1]}": v
                                 for k, v in sorted(adjud.items())},
            "by_check": {k: dict(v) for k, v in
                         sorted(adjud_by_check.items())},
            "filled_total": sum(adjud.values()),
        },
    }


def write_csv(summary, path: Path):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["check", "cases", "cases_with_findings",
                    "findings_total", "margin_count"]
                   + [f"margin_{label}" for label in MARGIN_LABELS])
        for code, s in summary["per_check"].items():
            w.writerow([code, s["cases"], s["cases_with_findings"],
                        s["findings_total"], s["margin_count"]]
                       + [s["margin_histogram"][label]
                          for label in MARGIN_LABELS])


def main():
    ap = argparse.ArgumentParser(description="RoboAudit share bundle 집계")
    ap.add_argument("bundles_dir", help="share bundle JSON들이 모인 폴더")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본: bundles_dir)")
    args = ap.parse_args()
    folder = Path(args.bundles_dir)
    if not folder.is_dir():
        print(f"error: {folder} 폴더가 없습니다", file=sys.stderr)
        return 2
    bundles, skipped = load_bundles(folder)
    for name, why in skipped:
        print(f"skip: {name} ({why})", file=sys.stderr)
    if not bundles:
        print("error: 집계할 share bundle이 없습니다", file=sys.stderr)
        return 2
    summary = aggregate(bundles)
    out_dir = Path(args.out) if args.out else folder
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cases_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(summary, out_dir / "cases_summary.csv")
    print(f"cases: {summary['cases']} "
          f"(episodes {summary['episodes_total']}, "
          f"formats {summary['format_distribution']}, "
          f"grades {summary['grade_distribution']})")
    print(f"wrote: {out_dir / 'cases_summary.json'}, "
          f"{out_dir / 'cases_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
