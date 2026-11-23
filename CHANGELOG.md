# Changelog

All notable changes to RoboAudit are documented here.
Rules version is tracked separately inside every report's run manifest
(`rules-2026-11-23.1` as of 0.3.2).

## [0.3.2] - 2026-11-23

Five new checks (17 total) and the workflow features around them. All
new thresholds are provisional working values; their grounds are stated
in the README's "New in 0.3.2" section and in the code.

### New checks

- **S4 recorded-statistics drift** (warning, −3): recomputes per-feature
  mean/std deterministically and compares them with the recorded stats
  (dataset-level `meta/stats.json` and per-episode recorded stats, both
  formats). Flags a recorded mean off by > 0.1σ or a recorded std off
  by > 0.1σ (0.1σ mean-shift criterion as published by the kinema
  dataset tool).
- **S5 dataset-card defaults** (info, −1): no `license` field in the
  dataset card, or the LeRobot template default `apache-2.0` left in
  place with an untouched template body. A local copy without a card
  is not flagged.
- **A5 near-duplicate episodes** (info, −1): deterministic trajectory
  signatures (16 resampled points, σ-normalised) catch episode pairs
  that are near-copies but not byte-identical (A4's territory).
- **A6 idle ratio** (warning, −3): episodes with ≥ 30% bit-identical
  consecutive action frames, or ≥ 20% leading idle.
- **A7 calibration drift** (warning, −3): systematic median
  state−action offset > 0.5× the state spread (reported from 0.25×)
  when state/action share dimension names and the offset is consistent.

### New features

- **Review shortlist**: episodes ranked for human review (robust
  outlier score over jerk p95, max step, idle ratio, final-pose
  distance, then finding count), a per-episode metrics table
  (`episode_metrics` in result.json), and copyable
  `lerobot-edit-dataset` delete commands for the excluded set —
  printed only, never executed.
- **CI gate**: `--fail-under N` exits with code 1 when the score is
  below N. Exit-code contract otherwise unchanged (0 complete,
  2 input error, 3 incomplete; 3 takes precedence over 1). A GitHub
  Action wrapper (`action.yml`) ships with the repository.
- **Visualizer deep links**: when the Hub repo-id is known (Hub input
  or `--repo-id`), finding rows in `report.html` link to the official
  LeRobot dataset visualizer episode page. No link is ever fabricated
  for unknown datasets.
- **`--markdown`** writes `report.md`; **`badge.svg`** (score/grade)
  is now always written.
- **`roboaudit diff old.json new.json`**: score/grade delta, per-check
  finding-count changes, added/removed findings, disposition changes.
- **Per-task scores**: `task_scores` in result.json and a task table
  in the reports (episode-level deductions grouped by task;
  dataset-level deductions reported separately).
- **Hub input**: pass a repo-id instead of a local folder (optional
  `roboaudit[hub]` extra), pin with `--revision`, and sample-audit
  large datasets with `--max-episodes N` (dataset-wide checks that
  need every episode are skipped or restricted, and say so).

### Verification

- Regression: planted-defect suites still 17/17 and 26/26, zero
  false positives on clean data, original files SHA-256 unchanged.
  Each new check has its own planted-defect fixture (detected) and
  stays silent on clean data.
- The original 12 checks reproduce their 0.3.1 findings **exactly**
  on all ten public datasets re-audited. Scores moved only where the
  new checks genuinely fired: aloha_sim_transfer_cube_scripted
  79/C → 77/C (A5 near-duplicate pair, S5 template license),
  so100_battery 84/B → 71/C (four A6 idle episodes at 31–38% frozen
  frames — one episode excluded on a 31% leading freeze — plus S5),
  sreetz vials unchanged at 44/F.

## [0.3.1] - 2026-11-17

A bug fix found by our own Report Cards audit series, plus the
diagnostic rework promised in the forum thread. No check threshold,
scoring, or disposition rule changed: the three published baselines
are reproduced exactly (aloha 79/C, so100_battery 84/B, sreetz vials
44/F), and of the ten public datasets audited for Report Cards #02,
nine return identical scores and dispositions under 0.3.1. The one
that moves is the one the bug was manufacturing findings in.

- **BUG FIX — frame-exact video segment decoding.** Episode segments
  decoded from large shared video files were sliced with an
  ffmpeg `-ss`/`-t` window whose start and duration were rounded to
  milliseconds. On shared files that produced three failure shapes:
  one frame too many (the next episode's first frame admitted by the
  rounded duration), one frame too few (window truncated), and —
  worst — a silent one-frame shift with the correct count, which no
  finding ever reported. Segments are now decoded frame-exactly:
  seek to half a frame before the segment start, then cap the output
  at the declared frame count (`-frames:v N`). Verified pixel-identical
  to a full sequential decode at the first, middle, and last episodes
  of an 800-episode shared file, at unchanged audit speed.
  **Effect:** `lerobot/xarm_lift_medium`, reported as 0/F in the
  Report Cards #02 audits under 0.3.0 (435 false "video frames ≠ meta
  length" findings, −1,305 points, all artifacts of this reader bug —
  the file holds exactly 20,000 frames = 800 × 25), corrects to
  **80/B** (796 keep / 4 review / 0 exclude; the remaining findings
  are one A1 excursion, three V2 warnings, and the standing L2 note).
  The other nine audited datasets are unchanged — their segment
  geometry never crossed the millisecond rounding boundary (the bug
  needs a segment duration whose rounding crosses a frame boundary,
  e.g. 25 frames at 15 fps).
- **Timestamp diagnostic split into two axes.** The single grid
  verdict is now reported as two independent questions —
  `clock_provenance` (`synthetic_grid` vs `real_or_unverified`) and
  `interval_regularity` (`uniform` / `widened_at_points` /
  `irregular`) — composed into the report's timestamp line, so the
  report can no longer call timestamps "uninformative" in one place
  while another check reports the widened intervals. Gaps in
  `frame_index` itself are reported as a separate labelled signal,
  `index_gaps`, meaning **rows removed after recording** (a
  capture-time recorder writes contiguous indices). The signal is
  index-derived, not a clock: it never opens the interval-ratio gate,
  never yields a ratio, and an A2 finding at a gap carries it as a
  separate `index_gap_at_jump` evidence block, distinct from interval
  evidence. The legacy `is_grid` / `informative` fields keep their
  0.3.0 semantics; the ratio gate still opens only on real-clock data.
- **A2 state-absent evidence is explicitly unresolved.** A
  `state-absent` finding now carries a `state_note` stating that the
  state neither stepped with the command nor followed within 10
  frames, and that this is an observation — not evidence for a fast
  command or for a dropped frame. (The label itself is unchanged, for
  comparability with the published cross-checks.)
- Rules version is now `rules-2026-11-17.2`.

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
