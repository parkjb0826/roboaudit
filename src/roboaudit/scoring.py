"""건강 점수: 심각도 가중 감점 (설계서 v1 — 치명 -10, 경고 -3, 참고 -1), 100점 만점, 등급 A~F."""
from .checks12 import SEVERITY

DEDUCTION = {"critical": 10, "warning": 3, "info": 1}

GRADE_BANDS = [(90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F")]


def grade_of(score: int) -> str:
    for lo, g in GRADE_BANDS:
        if score >= lo:
            return g
    return "F"


def score_findings(findings):
    """findings -> (점수, 등급, 검사별 감점 요약)."""
    per_check = {}
    total = 0
    for f in findings:
        d = DEDUCTION[f["severity"]]
        total += d
        c = per_check.setdefault(f["check"], {"findings": 0, "deduction": 0,
                                              "severity": f["severity"]})
        c["findings"] += 1
        c["deduction"] += d
    score = max(0, 100 - total)
    return score, grade_of(score), per_check
