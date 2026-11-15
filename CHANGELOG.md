# Changelog

All notable changes to RoboAudit are documented here.
Rules version is tracked separately inside every report's run manifest
(`rules-2026-11-15.2` as of 0.2.2).

## [0.2.2] - 2026-11-16

Opt-in case sharing only — no changes to checks, thresholds, or
disposition criteria, and nothing is ever transmitted automatically.

- **Share bundles (opt-in, off by default)**: `roboaudit share
  <result.json>` — or `--share-bundle` at audit time — writes a
  `share_bundle.json` containing an anonymised summary only: tool/rules
  versions, dataset format, episode/frame/camera/task counts, score and
  grade, per-check finding counts and margin-ratio distributions,
  disposition and run-status totals, and sampling-mode flag. The bundle
  is built by whitelist extraction and never contains dataset names,
  paths, file names, task text (or hashes of it), raw data values,
  camera/feature key names, robot type, or the input fingerprint.
  Verified by a leak check over three real audit results (33 forbidden
  strings, 0 hits).
- **Adjudication template**: each bundle carries one empty entry per
  flagged episode (`verdict: agree / false_positive / unsure`) so users
  can record human judgements — the raw material for validating the
  provisional thresholds.
- **Submission channel**: a GitHub issue template
  (`.github/ISSUE_TEMPLATE/audit-case.yml`) with a mandatory privacy
  self-check; submitted bundles become the case database, no server
  required.
- **Operator aggregation**: `tools/collect_cases.py` folds a folder of
  bundles into `cases_summary.json` / `cases_summary.csv` (case counts,
  format/grade distributions, per-check finding frequencies, summed
  margin histograms, adjudication tallies).

## [0.2.1] - 2026-11-16

Notices, escaping, and output safety only — no changes to checks,
thresholds, or disposition criteria.

- Reports and `result.json` now carry explicit scope notices: sampling-mode
  results are approximate (final verdicts should use a full audit), and an
  A2 "review" disposition means the tool cannot distinguish a recording
  defect from a robot's operating characteristics.
- HTML reports are rendered with autoescaping (dataset text can no longer
  inject markup into a report).
- The CLI now refuses, before auditing, an `--out` directory located inside
  the input dataset folder (exit code 2) to prevent contaminating the
  original data.

## [0.2.0] - 2026-11-15

Honesty, dispositions, and reproducibility. Detection logic and thresholds
unchanged from 0.1.

- **Per-check run status**: every check records
  `complete / partial / not_applicable / error` plus the actual scope it
  covered (per-camera decode success/failure/missing counts). If any
  required check is partial or errored, the audit is flagged
  `incomplete_audit` and the report shows a warning banner — a failed check
  can no longer silently look like a pass.
- **Three-way dispositions**: episodes are now `exclude` (clear violation),
  `review` (borderline — margin ratio below 1.5, or info-level findings
  only), or `keep`. Borderline episodes are written to a new
  `review_index.json` instead of being silently dropped or kept.
- **Top-3 deduction factors** are summarised in `result.json` and at the
  top of the HTML report.
- **Run manifest** in `result.json`: tool version, rules version, all
  thresholds actually applied, an input fingerprint (SHA-256 over the
  dataset file list), per-camera decode statistics/backends, and sampling
  mode. Re-running the same input reproduces the same score, findings,
  dispositions, and fingerprint.
- **All declared cameras are audited** (previously only one representative
  camera). A camera whose files are missing is reported, not skipped.
- **Sampling mode** (`--sample-frames N`): video statistics from an evenly
  spaced sample of up to N frames per episode, for very large datasets.
- Documented CLI exit codes: 0 = complete audit, 3 = incomplete audit,
  2 = input error, 1 = unexpected failure.

## [0.1.0] - 2026-11-15

Initial version.

- LeRobot v2.1 and v3.0 datasets read with a built-in parser (no conversion
  step; v2.1 is read directly even though the current official library
  refuses to load it).
- 12 rule/threshold checks: structure S1–S3, video V1–V3, action A1–A4,
  instruction L1–L2. No AI inside the checks; every deduction is traceable
  to a rule and a measured value.
- Severity-weighted 100-point score and grade (critical −10, warning −3,
  info −1).
- Outputs: `report.html`, `result.json`, `clean_index.json`
  (episodes safe to keep). Original data is read-only and never modified.
- Validation at release time: 43/43 injected defects detected across both
  formats, 0 false positives on clean data, input hashes unchanged.
