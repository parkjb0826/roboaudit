---
title: RoboAudit Demo
emoji: 🩺
colorFrom: blue
colorTo: green
sdk: gradio
app_file: app.py
pinned: false
---

# RoboAudit demo (not yet deployed)

A fixed-data demo for [RoboAudit](../README.md), the LeRobot dataset
health-check CLI.

- Choose one of three pre-audited public datasets; the app shows the
  stored score summary and the full HTML report produced by RoboAudit
  0.2.1.
- **No arbitrary uploads.** Auditing is CPU-heavy (minutes per dataset),
  so the first public demo ships with fixed data on purpose. Upload
  support would need a queue, size limits, and abuse controls.
- Demo data lives in `demo_data/<dataset>/` (`result.json`, `report.html`,
  `clean_index.json`, `review_index.json`) and is copied verbatim from
  real audit runs.

Local syntax check only (no deployment):

```bash
python -m py_compile app.py
```
