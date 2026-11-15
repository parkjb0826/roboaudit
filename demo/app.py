"""RoboAudit demo (Hugging Face Spaces).

Fixed-demo design: visitors pick one of three pre-audited public datasets
and see the stored RoboAudit report. Arbitrary uploads are intentionally
NOT accepted in this first demo — auditing is CPU-heavy and an open upload
endpoint would need queueing, limits, and abuse controls first.

The audit results under demo_data/ were produced by RoboAudit 0.2.1
(rules rules-2026-11-15.2) on the datasets' public copies.
"""
import json
from pathlib import Path

import gradio as gr

DATA_DIR = Path(__file__).resolve().parent / "demo_data"

DATASETS = {
    "lerobot/aloha_sim_transfer_cube_scripted (v3.0, 50 ep)":
        "aloha_sim_transfer_cube_scripted",
    "00ri/so100_battery (v2.1, 50 ep)":
        "so100_battery",
    "sreetz-nv/so101_teleop_vials_rack_left (v3.0, 75 ep, partial copy)":
        "sreetz_so101_teleop_vials",
}


def load_result(folder: str) -> dict:
    return json.loads((DATA_DIR / folder / "result.json").read_text())


def load_report_html(folder: str) -> str:
    return (DATA_DIR / folder / "report.html").read_text(encoding="utf-8")


def summary_md(result: dict) -> str:
    s = result["summary"]
    lines = [
        f"## Score: {result['score']}/100 — Grade {result['grade']}",
        "",
        f"- Dataset: `{s['dataset']}` (LeRobot {s['format']}, "
        f"{s['total_episodes']} episodes)",
        f"- Findings: {len(result['findings'])} "
        f"(total deduction {result['total_deduction']})",
        f"- Keep: {len(result['clean_episodes'])} episodes · "
        f"Review: {len(result['review_episodes'])} · "
        f"Exclude: {len(result['excluded_episodes'])}",
        f"- Incomplete audit: {'YES — see report' if result['incomplete_audit'] else 'no'}",
        "",
        "**Top deduction factors**",
        "",
    ]
    for f in result.get("top_factors", []):
        lines.append(
            f"- {f['check']} {f['name']}: {f['findings']} finding(s), "
            f"-{f['deduction']} pts ({f['share_pct']}%)")
    lines += [
        "",
        "> The score is a relative indicator, not an absolute quality "
        "measure, and says nothing about training performance or robot "
        "safety. See the README for limitations.",
    ]
    return "\n".join(lines)


def show(label: str):
    folder = DATASETS[label]
    result = load_result(folder)
    return summary_md(result), load_report_html(folder)


first_label = next(iter(DATASETS))

with gr.Blocks(title="RoboAudit demo") as demo:
    gr.Markdown(
        "# RoboAudit — LeRobot dataset health check\n"
        "Pick one of three pre-audited public datasets to see a real "
        "RoboAudit report (score, findings, episode dispositions). "
        "This demo is fixed-data only; arbitrary uploads are not accepted.")
    picker = gr.Dropdown(
        choices=list(DATASETS), value=first_label, label="Demo dataset")
    summary = gr.Markdown()
    report = gr.HTML()
    picker.change(show, inputs=picker, outputs=[summary, report])
    demo.load(show, inputs=picker, outputs=[summary, report])

if __name__ == "__main__":
    demo.launch()
