# Launch post (draft) — Show HN / Hugging Face forum

## Title candidates

1. Show HN: RoboAudit — a health check for LeRobot datasets, before you train on them
2. I audited three public robot datasets. One was missing an entire camera.
3. Before you train on it, audit it: rule-based dataset audits for LeRobot (v2.1 and v3.0)

## Body

Every robot-learning practitioner has a version of this story. You collect
or download a dataset, start a training run, and check back hours or days
later to find the policy learned garbage — because some of the data was
garbage to begin with. A camera stream that silently stopped being
recorded. Episodes with NaN actions. Timestamps that run backwards. Task
instructions that were never filled in. None of these throw an error at
load time; they just quietly eat your compute budget.

RoboAudit is the inspection I wanted to run *before* that training run.
It is a small CLI for LeRobot datasets — no robot, no GPU, CPU only:

```
git clone https://github.com/parkjb0826/roboaudit
cd roboaudit && pip install .
roboaudit /path/to/dataset --out ./audit_out
```

It runs 12 rule-and-threshold checks (structure, video, action,
instruction — no AI inside the checks, so every deduction traces back to
a rule and a measured value) and produces a report card: a 100-point
score with a grade, the findings behind it, and an episode-level
disposition — **exclude**, **review**, or **keep** — written as index
files for selecting which episodes to train on. The original dataset is only
ever read, never modified.

Three numbers from our own testing:

1. **Planted-defect test: 43/43 detected** — on a suite where we planted
   43 known defects across both LeRobot formats, RoboAudit caught all of
   them with zero false-positive verdicts on 40 clean synthetic episodes. The comparable
   open-source auditor (RDA, on PyPI) reached a verdict on 22 of the
   same 43. Fair warning: we built the test suite, so it is a home-field
   result — RDA is more conservative by design and has its own blind
   test.
2. **Legacy v2.1 datasets are audited directly, without conversion** —
   RoboAudit ships its own parser, so it reads the format that, with
   LeRobot 0.7.0, the official loader refuses to load
   (BackwardCompatibilityError).
3. **On real public data it stays honest about uncertainty.** Auditing
   three Hub datasets gave 79/C, 84/B, and 44/F. The F was a partial
   copy missing one camera's files entirely — instead of passing it
   silently, the audit flags itself *incomplete*. Borderline episodes
   (a "shake" flag that is really just a busy episode) go to `review`
   for a human, not into the bin.

The limitations are real, and they are printed in the report: the score
is a relative indicator, not an absolute quality measure; nothing here
guarantees better training outcomes; and the borderline threshold
(1.5×) is provisional — calibrated on synthetic injections plus a
handful of real datasets.

That last point is why I am posting. RoboAudit has an opt-in case
sharing mechanism: `roboaudit share` produces a whitelist-extracted summary
(counts, score, per-check finding and margin distributions — never
names, paths, task text, or raw values) that you can paste into a
GitHub issue, with a template to mark findings you judged to be false
positives. If you run it on your dataset, I would genuinely like to see
the case: adjudicated real-world audits are what turns a provisional
threshold into a validated one.

The code, the full measured results, and the comparison method are in
the repository. Criticism of the checks and thresholds is especially
welcome — that is the part that needs more eyes.
