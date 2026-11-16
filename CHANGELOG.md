# Changelog

All notable changes to RoboAudit are documented here.
Rules version is tracked separately inside every report's run manifest
(`rules-2026-11-17.1` as of 0.3.0).

## [0.3.0] - 2026-11-17

Timestamp honesty and richer A2 evidence — evidence only. No check,
threshold, score, grade, or disposition changed: the three published
real-dataset baselines are reproduced exactly (aloha 79/C,
so100_battery 84/B, sreetz vials 44/F, with identical dispositions).

This release was prompted by community feedback on the Hugging Face
forum: a reader proposed splitting A2 jump findings by the frame
interval across each jump — a stretched interval suggests a dropped
frame, a normal one a fast command. Testing that idea showed the
timestamps in the audited datasets are a synthetic
`frame_index / fps` grid, which carries no capture-timing information
at all — so the split is now implemented but gated on the timestamps
actually being informative.

- **Timestamp-grid diagnostic**: every audit now measures whether the
  timestamp column is a synthetic `frame_index / fps` grid (per-episode
  max deviation, interval-deviation and frame-gap counts). The result
  is recorded as a top-level `diagnostics` block in `result.json` and
  shown as a plain-language line in the HTML report — e.g.
  "Timestamps: synthetic grid (frame_index/fps) — interval-based
  reasoning not applicable" or "Timestamps: informative (real capture
  timing)". It is a diagnostic, not a 13th check, and is not scored.
  All three published report-card datasets turned out to be
  grid-timestamped (max deviation ≤ 9×10⁻⁷ s).
- **Gated A2 interval-ratio evidence**: when — and only when — the
  diagnostic marks timestamps as informative, each A2 finding now
  carries `interval_ratio` (interval across the jump ÷ the episode's
  median interval) and `interval_class` (`dropped-frame-looking` at
  ratio ≥ 1.5, `normal-interval` at 0.8–1.25, otherwise `ambiguous`).
  On grid-timestamped data the fields are `interval_ratio: null` with
  an `interval_note` stating why. Evidence only — the ratio does not
  change any disposition in this version.
- **A2 state-following evidence**: each A2 finding on the action column
  now records the dominant action dimension, the `observation.state`
  step at the jump frame, the state's follow-through within the next
  10 frames (and the fraction of the action step it covers), and a
  `state_label` (`state-simultaneous` / `state-follows` /
  `state-absent`) — so a disposition can cite how the real joints
  responded, not just the size of the command jump. On the sreetz
  vials findings this reproduces the published follow-up analysis
  exactly (14 state-follows, 1 state-absent, 0 state-simultaneous;
  gripper dominant in only 2 of 15).
- Rules version is now `rules-2026-11-17.1`.

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
