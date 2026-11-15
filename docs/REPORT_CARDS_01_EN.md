# Report Cards #01 — Three public LeRobot datasets, audited

*The first in a series: we run RoboAudit on public LeRobot datasets and
publish the report cards, including the parts where the tool itself is
unsure. Scores are relative indicators, not absolute quality measures —
and nothing here says anything about how well a policy trained on the
kept episodes will perform.*

Tool: RoboAudit 0.2.x · 12 rule/threshold checks · full audit (no sampling)

Repository: https://github.com/parkjb0826/roboaudit · These same three
report cards are browsable in the static demo (precomputed reports, no
live auditing): https://huggingface.co/spaces/jbpark0826/roboaudit-demo

*Calibration note: these are the same three datasets used to calibrate
the disposition thresholds, so read their grades as in-sample results.*

---

## 1. `lerobot/aloha_sim_transfer_cube_scripted` — **79 / C**

Format v3.0 · 50 episodes · keep 48 · review 2 · exclude 0

The official ALOHA simulation dataset is structurally clean: file
integrity, schema, time axis, video lengths, and instructions all pass,
and all 50 episodes of its single camera decode fine. The entire
deduction comes from two episodes (45 and 46) whose action values sit
just past the edge of the dataset's own range band, plus a standing
note that the dataset carries no success/failure labels.

Why review and not exclude: the two episodes exceed the band edge by
only 0.44 and 0.28 of the margin that would justify automatic
exclusion, and they do not repeat the pattern across the dataset. That
is exactly the shape of "local excursion or recording quirk — a human
should look." An earlier version of RoboAudit excluded these outright;
the review disposition exists because that call was not defensible.

## 2. `00ri/so100_battery` — **84 / B**

Format v2.1 · 50 episodes · keep 45 · review 5 · exclude 0

A community SO-100 recording in the legacy v2.1 format — the format
that, with LeRobot 0.7.0, the official loader refuses to load
(BackwardCompatibilityError). RoboAudit's own parser reads
it directly, both declared cameras (laptop and phone) decode for all 50
episodes, and the phone camera produces no findings at all.

The five findings are all V2 "shake" flags on the laptop camera, with
margins between 1.02 and 1.41 — every one below the 1.5 exclusion line.
Looking at the measurements, these episodes are most plausibly *busy*
episodes (more motion than the dataset median) rather than a shaking
camera: the check compares an episode's frame-to-frame change against
the dataset median, and high-motion episodes trip it. We deliberately
did not raise the threshold to make them disappear — the same setting
is what catches genuinely planted shake in the defect suite. So all
five are reported as review, with the reason printed. That is the
honest answer this tool can give; pretending certainty either way
would be worse.

## 3. `sreetz-nv/so101_teleop_vials_rack_left` — **44 / F** (partial copy)

Format v3.0 · 75 episodes · keep 60 · review 8 · exclude 7 · **audit incomplete**

Two separate stories in one score. First: the copy we audited declares
two cameras, and one of them (the ego camera) has **no files at all** —
every episode is missing it. RoboAudit records that as a dataset-level
critical finding, marks the video checks partial, and stamps the whole
audit **incomplete** (exit code 3). A missing camera must never
masquerade as a passed check. To be plain about whose gap this is: our
copy was a partial download (166 MB) that included only one of the two
declared cameras, so the missing camera is a property of this copy —
the upstream dataset as published may well be complete, and the 44/F
grades the copy we held, not necessarily the original.

Second: the camera that *is* present shows 15 abrupt-jump (A2)
findings — command discontinuities of roughly 21°–43°, against a
dataset-relative floor of about 21°. This check cannot distinguish a
recording defect (dropped frames) from a genuinely fast operator
command, and we say so in the report. What the tool *can* do is split
by measured strength: 7 episodes at or beyond 1.5× the threshold are
excluded, 8 below it go to review. Read the 44/F as "a teleoperation
recording with frequent discontinuities, partly unverifiable" — not
simply "bad data."

---

## What these three taught us

- The interesting output is rarely the score. It is *which* episodes,
  *why*, and *how sure the tool is* — that is why borderline findings
  go to a human instead of being silently dropped or silently kept.
- Real data punishes naive thresholds: our first pass at these datasets
  produced hundreds of false positives (multimodal action distributions
  tripping range fences, still segments inflating shake ratios). The
  checks in the current release are the ones that survived that
  measurement process, regression suite included.

**Next in the series:** a v2.1 community dataset with four cameras, and
a revisit of the jump (A2) question — how many of those discontinuities
are dropped frames? If you have a public dataset you would like
audited, or you ran RoboAudit on your own and want to share the
case (opt-in; the shared bundle is a whitelist-extracted summary,
not your data), the issue template in the repository is the
way in.
