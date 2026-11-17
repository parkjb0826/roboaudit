# RoboAudit

**Before you train on it, audit it.** RoboAudit is a health-check CLI for
[LeRobot](https://github.com/huggingface/lerobot) robot datasets: give it a
dataset folder and it returns a **100-point score with a grade**, a list of
what is wrong and where, and episode indexes that sort episodes into
keep / review / exclude for training-data selection.

![RoboAudit pipeline: a LeRobot dataset (v2.1 or v3.0) goes through 12 rule-based checks in four groups — structure, video, action, instruction — and comes out as a 100-point score with a grade, top-3 deduction factors, and four output files: report.html, result.json, clean_index.json, and review_index.json, plus an optional opt-in share bundle.](docs/img/flow.svg)

> **Why it exists**
>
> 1. **Planted-defect test: 43/43 detected** — the comparable open-source
>    auditor caught 22 at verdict level.\*
> 2. **Audits legacy v2.1 datasets directly, without conversion** — with
>    LeRobot 0.7.0, the official loader refuses v2.1 datasets
>    (BackwardCompatibilityError); RoboAudit's own parser reads them.
> 3. **Not just a score:** exclude / review / keep episode indexes for
>    selecting which episodes to train on.
>
> \* The defect suite was built by the RoboAudit authors — a home-field
> test, so read it as one. Full comparison in
> [How it compares](#how-it-compares) below.

## Quick start

```bash
pip install roboaudit
roboaudit /path/to/lerobot_dataset --out ./audit_out
```

> ⚠️ `--out` must point **outside** the dataset folder. If it points
> inside, the run is refused (exit code 2) — this protects the original
> data from ever being written into.

That writes `report.html` (the report card), `result.json`,
`clean_index.json`, and `review_index.json` into `./audit_out`. No robot,
no GPU — CPU only. Getting to the first command takes about a minute;
the audit itself takes minutes, not seconds — measured on this
project's (small, shared) VM CPU: 152–180 s for 50–75-episode datasets
with one camera decoded, and 296 s for a 50-episode dataset with two
cameras decoded. Details (Python version, optional ffmpeg, sampling
mode, exit codes) are in [Install](#install) and [Usage](#usage) below.

## Report cards from real datasets

![Report cards for three real public datasets: aloha transfer cube (sim) scores 79 out of 100, grade C, with 0 episodes excluded and 2 sent to review; so100_battery scores 84, grade B, with 0 excluded and 5 in review; so101_teleop_vials (partial copy) scores 44, grade F, flagged as an incomplete audit, with 7 excluded and 8 in review.](docs/img/report_cards.svg)

Real audits of three public datasets — not demos, not synthetic data
(full method and caveats in [Measured results](#measured-results-not-marketing-numbers)).
One caveat up front: these three datasets were also used to calibrate
the disposition thresholds, so read their grades as in-sample results:

| Dataset | Format | Episodes | Score | Exclude / Review | One-line verdict |
|---|---|---|---|---|---|
| `lerobot/aloha_sim_transfer_cube_scripted` | v3.0 | 50 | **79 / C** | 0 / 2 | Two episodes sit just past a range-band edge (measured at 0.28–0.44 of the exclusion margin) — sent to a human, not dropped |
| `00ri/so100_battery` | v2.1 | 50 | **84 / B** | 0 / 5 | Five "shake" flags that look like busy episodes rather than camera shake — all review, none auto-dropped; both declared cameras audited |
| `sreetz-nv/so101_teleop_vials_rack_left` (partial copy) | v3.0 | 75 | **44 / F** | 7 / 8 | Audited from a **partial copy** (a 166 MB download covering only one of the two declared cameras): the missing camera is a property of this copy — the upstream dataset may be complete. The audit is flagged **incomplete** instead of passing silently; 15 jump findings split by measured strength |

## How it compares

![Bar chart of the planted-defect test with 43 known defects: RoboAudit reached a verdict on all 43; RDA 0.12.4 reached a verdict on 22 (15 exclude plus 7 unverifiable), recorded 2 more as findings only, and the remaining 19 fell outside its check set. The defect suite was built by the RoboAudit authors — a home-field test.](docs/img/detection_compare.svg)

Head-to-head with RDA (Robot Data Audit, the comparable open-source
auditor on PyPI), run on the same data in its full mode (`--full`, every
check enabled) but without a platform profile:

| | RoboAudit | RDA 0.12.4 |
|---|---|---|
| Planted defects (43) reaching a verdict | **43** | 22 (15 exclude + 7 correctly pinpointed as unverifiable) |
| Recorded as a finding only (no verdict) | 0 | 2 |
| Outside the tool's check set (no verdict, no finding) | **0** | 19 — check types RDA does not implement (state jumps, range violations, dead dimensions, duplicates, instruction problems, episode boundaries) |
| False-positive verdicts on clean data (40 episodes) | 0 | 0 |
| Behaviour on the 3 real datasets above | Borderline findings → `review` | All-pass on the two complete datasets; refused a verdict on the partial copy |

Read this fairly: the defect suite is RoboAudit's home field, RDA was run
without a platform profile (its joint-limit check needs one), and RDA has
its own separate blind test. On real data RDA is the more conservative
design — it records risk signals at metric level without letting them
change verdicts. RoboAudit's difference is breadth of checks that *do*
reach a verdict, plus dispositions a human can overrule.

## Demo

A fixed-data demo lives in [`demo/`](demo/): pick one of the three
pre-audited datasets above and browse its stored score summary and full
HTML report. The demo files are prepared and verified locally; the demo
itself is not deployed yet. Arbitrary uploads are deliberately not
supported — auditing is CPU-heavy (minutes per dataset), so a public
demo needs a queue and abuse controls first.

---

The idea is simple: robot training is expensive, and a dataset with missing
videos, NaN actions, reversed timestamps, or broken instructions wastes that
money silently. RoboAudit is the cheap inspection you run *before* training.

- Reads **LeRobot v2.1 and v3.0** with its own parser — no conversion step.
  v2.1 is read directly, even though with LeRobot 0.7.0 the official
  loader refuses v2.1 datasets (BackwardCompatibilityError).
- **12 rule/threshold checks** (structure, video, action, instruction).
  No AI inside the checks: every deduction traces back to a rule and a
  measured value, so a score can always be explained.
- **Original data is read-only.** RoboAudit never modifies the dataset
  (verified by SHA-256 before/after in its own test suite).
- No robot, no GPU. CPU only.

## Install

```bash
pip install roboaudit
```

Or install from source instead:

```bash
git clone https://github.com/parkjb0826/roboaudit
cd roboaudit
python3 -m venv .venv && source .venv/bin/activate   # recommended
pip install .
```

Requires Python ≥ 3.10 (developed and verified on Linux with
Python 3.12; other platforms are untested).
Runtime dependencies: `numpy`, `opencv-python-headless`, `pyarrow`, `jinja2`.

Optional: if a system `ffmpeg` binary is on your `PATH`, it is used as a
fallback decoder for video codecs OpenCV cannot read (e.g. AV1).

## Usage

Basic audit — writes `report.html`, `result.json`, `clean_index.json`, and
`review_index.json` into the output folder:

```bash
roboaudit /path/to/lerobot_dataset --out ./audit_out
```

The argument is the dataset **root folder on local disk** — RoboAudit
does not download anything, so fetch the dataset first (e.g. from the
Hugging Face Hub). The root is the folder that contains `meta/info.json`:

```
my_dataset/                       ← pass this folder
├── meta/
│   ├── info.json
│   ├── episodes/chunk-000/file-000.parquet
│   └── tasks.parquet
├── data/chunk-000/file-000.parquet                 (shared across episodes)
└── videos/observation.images.top/chunk-000/file-000.mp4
```

That is the v3.0 layout. The v2.1 layout differs — per-episode files
(`data/chunk-000/episode_000000.parquet`,
`videos/chunk-000/<camera_key>/episode_000000.mp4`, `meta/episodes.jsonl`)
— and is read directly as well. If `meta/info.json` is missing, the
command stops with exit code 2 (see [Troubleshooting](#troubleshooting)).

Sampling mode for very large datasets — video statistics are computed from
an evenly spaced sample of at most N frames per episode instead of every
frame. Faster, but approximate (see *Limitations*):

```bash
roboaudit /path/to/big_dataset --out ./audit_out --sample-frames 60
```

Exit codes are part of the interface, so the tool can gate a pipeline:

| Code | Meaning |
|---|---|
| 0 | Audit complete — every check covered its full scope (regardless of how many defects were found) |
| 1 | Unexpected runtime failure |
| 2 | Input error — not a LeRobot dataset folder, or `--out` points inside the dataset folder (refused, to protect the original data) |
| 3 | Audit finished but **incomplete** — some check ran partially or errored; the report says which and why |

**Exit code 0 means the audit ran to completion with full coverage. It
does NOT mean the dataset passed** — a complete audit can still find
critical defects and score an F. If you gate a pipeline on RoboAudit,
check the score and findings in `result.json` too, and treat exit
code 3 (incomplete) as "the indexes are not final" (see
[Score and dispositions](#score-and-dispositions)).

## Outputs

| File | Contents |
|---|---|
| `report.html` | Human-readable report card: score and grade, top-3 deduction factors, per-check run status and findings, per-camera decode statistics, a timestamp-provenance line (see below), scope notices |
| `result.json` | Machine-readable full result, including a **run manifest** (tool/rules versions, thresholds actually applied, input fingerprint, decode backends) to help reproduce runs and compare their settings and results, plus a **diagnostics** block recording the timestamp diagnostic on two axes — clock provenance (whether the timestamps are a synthetic `frame_index / fps` grid) and interval regularity — plus any `frame_index` gaps as a separate signal |
| `clean_index.json` | The episode index file: `clean_episodes` (episodes assigned `keep`), plus the `excluded_episodes` and `review_episodes` lists with the checks that flagged each one |
| `review_index.json` | Borderline episodes a human should look at before deciding — these are **not** in `clean_episodes` (see below) |

Episode indices everywhere are the dataset's own `episode_index`
values from its metadata. The three lists are disjoint and together
cover every episode: an episode appears in exactly one of
`clean_episodes`, `review_episodes`, or `excluded_episodes`. Excluded
episodes appear in neither the keep list nor the review list — they
are recorded, with the checks that flagged them, in the
`excluded_episodes` field of `clean_index.json` and in `result.json`.

### Using the indexes in training code

```python
import json

index = json.load(open("audit_out/clean_index.json"))
result = json.load(open("audit_out/result.json"))

# 1. If the audit was incomplete, the indexes are not final — a check
#    that could not run may have missed defects (see report.html):
if result["incomplete_audit"]:
    raise SystemExit("Incomplete audit: indexes are not final")

keep = set(index["clean_episodes"])   # episode_index values with no finding
review = {e["episode_index"] for e in index["review_episodes"]}

# 2. Decide on the review episodes explicitly — do not drop them by
#    accident. Inspect them first, then name the ones you accept:
approved_after_review = set()  # e.g. {3, 17}, once you have looked

selected = sorted(keep | approved_after_review)

# 3. Pass the selection to your training set — with LeRobot, the
#    `episodes=` argument of LeRobotDataset takes exactly this list:
#    ds = LeRobotDataset("you/dataset", episodes=selected)
train_episodes = [ep for ep in my_episode_ids if ep in set(selected)]
```

`review_episodes` and `excluded_episodes` in the same file are lists of
`{"episode_index": …, "checks": […]}` objects, so you can see *why*
each episode was held back before deciding what to do with it.

## Share an audit case (opt-in)

RoboAudit's disposition thresholds (such as the 1.5× borderline margin)
are working values, not final constants: they were calibrated on
synthetic injections plus three real datasets and have not yet
been validated against many adjudicated real-world cases. The honest
way to validate them is to collect many real audit cases — which is
why RoboAudit has an **opt-in** case sharing mechanism.

**Nothing is ever sent automatically, and sharing is off by default.**
An audit run alone creates no shareable file. Only if you explicitly ask
for one do you get a `share_bundle.json`:

```bash
# from an existing audit result
roboaudit share path/to/audit_out/result.json

# or at audit time
roboaudit /path/to/dataset --out ./audit_out --share-bundle
```

The bundle is a **summary that omits the fields listed below**, built
by whitelist extraction from `result.json`. It contains only:

- tool and rules versions; dataset format (v2.1 / v3.0)
- episode, frame, camera and task **counts** (counts only)
- score and grade; per-check finding counts and severity counts
- per-check **margin-ratio distributions** (min / median / max and a
  histogram — ratios to thresholds, never raw measurements)
- disposition totals (exclude / review / keep) and run-status totals
- whether sampling mode was used

It **never** contains: dataset names, file or folder paths, file names,
task/instruction text (nor hashes of it — a hash can be a tracking
clue), video frames or images, raw sensor/action values, finding detail
text or evidence values, camera/feature key names, robot type, user or
machine information, or the dataset input fingerprint. Each bundle
states this in its own `about` field, so you can verify before sharing.
(This was verified mechanically: bundles generated from three real
audits were grepped for 33 forbidden strings — dataset names, real task
sentences, paths, key names — with 0 hits.)

Each bundle also carries an empty **adjudication template**: one entry
per flagged episode where you may record `agree`, `false_positive`, or
`unsure` after inspecting the episode yourself. Human-adjudicated cases
are the most valuable ones — they are what turns a working
threshold into a validated one.

To submit a case, open a GitHub issue with the **Audit case** template
and paste the bundle. The template asks you to confirm you checked the
file first. Submitted bundles are aggregated by the maintainers with
`tools/collect_cases.py` (included in this repository) into per-check
finding frequencies, margin distributions, and false-positive tallies.

## Score and dispositions

The score starts at 100, and **every recorded finding deducts by its
severity: critical −10, warning −3, info −1**. The score is floored
at 0. Most findings are recorded per affected episode — one per
episode for each problem a check finds — so the same defect in many
episodes deducts many times. A problem that is a property of the
dataset as a whole (a declared dimension that mismatches in every
episode, a missing feature declaration) is recorded **once**, not once
per episode. Because deductions accumulate per finding, the score is
not normalised by dataset size — compare scores within one dataset or
across versions of it (see *Limitations*). Grades: A ≥ 90, B ≥ 80,
C ≥ 70, D ≥ 60, F < 60.

Each episode also gets a disposition:

- **exclude** — a clear violation (missing file, NaN, structural break, or a
  measurement at least 1.5× past its threshold). Recorded in the
  `excluded_episodes` field of `clean_index.json` and in `result.json`;
  in neither the keep list nor the review list.
- **review** — borderline: a real finding, but too close to the threshold to
  condemn automatically. Listed in `review_index.json`, and **not** in
  `clean_episodes`. RoboAudit's design rule is *when in doubt, ask a
  human instead of silently dropping data*.
- **keep** — no finding was recorded for this episode by the checks
  that ran. Listed in `clean_index.json` (`clean_episodes`).

Score and disposition are computed independently, so the two do not
scale together. The score deducts per recorded finding by severity;
a disposition instead depends on how far past its threshold a
measurement sits (margin ratio ≥ 1.5× → exclude, below that → review;
info findings are always review, and findings with no measurable
margin — a missing file, a NaN — exclude at warning/critical
severity). Dataset-level findings deduct from the score but do not by
themselves change any episode's disposition. In the sreetz report
card, for example, the seven excluded episodes carry warning-level
jump findings (−3 each): the −56 total behind the 44 is 15 jump
warnings (−45) plus one dataset-level critical for the missing
camera (−10) and one info note (−1).

Separately, if any check could not cover its full scope (e.g. a camera's
files are missing, some videos failed to decode), the audit is flagged
**incomplete** in the report and via exit code 3. A failed check never
masquerades as a pass.

**Incomplete audits still write `clean_index.json`** — read it with the
flag in mind. There, `clean_episodes` means "no finding was recorded
by the checks that could run"; it does **not** mean the episode passed
the checks that could not run. In the sreetz report card above, the
partial copy we audited was missing one declared camera entirely, so
no episode was ever checked against it — yet 60 episodes are listed
as clean. Check
`incomplete_audit` in `result.json` (or the exit code) before treating
the list as final.

## The 12 checks

| Group | Checks |
|---|---|
| Structure | S1 metadata & file integrity · S2 dimension/schema consistency · S3 time axis (monotonic timestamps, episode boundaries) |
| Video | V1 black / frozen frames · V2 shake & blur · V3 episode length anomalies |
| Action | A1 out-of-range values · A2 abrupt jumps · A3 dead (never-moving) dimensions · A4 duplicate episodes |
| Instruction | L1 missing or identical task text · L2 no success/failure labels |

### Timestamp diagnostic and A2 evidence

Every audit also measures the dataset's timestamps themselves. Many
LeRobot datasets store timestamps synthesised as `frame_index / fps`,
which carry no capture-timing information. The audit reports what it
found on two independent axes — **clock provenance** (synthetic grid
vs real or unverified) and **interval regularity** (uniform, widened
at points, irregular) — as a line in `report.html` and a `diagnostics`
block in `result.json`, because any reasoning about *when* frames
happened is only valid when the timestamps are real. Gaps in
`frame_index` itself are reported separately, as an index-derived
signal meaning rows were removed after recording; they are not a
clock, never open the interval gate below, and never yield a ratio.
(All three report-card datasets above are grid-timestamped.)

A2 (abrupt jump) findings carry two extra pieces of evidence:

- **Interval ratio** — the frame interval across the jump divided by
  the episode's median interval, classified as `dropped-frame-looking`
  (≥ 1.5), `normal-interval` (0.8–1.25), or `ambiguous`. This is
  computed **only when the timestamps are informative**; on
  grid-timestamped data the field is `null` with a note saying why.
  It is evidence for a human reader — it does not change dispositions.
- **State following** — for the dimension that jumped, how the real
  joints (`observation.state`) responded: whether the state stepped at
  the same frame (`state-simultaneous`), followed over the next frames
  (`state-follows`), or showed no corresponding movement
  (`state-absent`). This lets a disposition cite behaviour, not just
  the size of the command jump. A `state-absent` result is explicitly
  unresolved — it is not evidence for a fast command or for a dropped
  frame.

Since 0.3.1, episode segments decoded from large shared video files
are sliced **frame-exactly** (seek to half a frame before the segment,
then cap at the declared frame count) instead of by a
millisecond-rounded time window. The old window could return one
frame too many, one too few, or — silently — the right count shifted
by one frame; on `lerobot/xarm_lift_medium` that reader bug alone
manufactured 435 false findings (corrected grade 80/B under 0.3.1;
see the changelog).

## Measured results (not marketing numbers)

On three real public datasets (audited on a small shared-CPU VM, roughly
2–5 minutes each):

| Dataset | Format | Episodes | Score | Notes |
|---|---|---|---|---|
| `lerobot/aloha_sim_transfer_cube_scripted` | v3.0 | 50 | **79 / C** | 2 borderline episodes sent to review |
| `00ri/so100_battery` | v2.1 | 50 | **84 / B** | 5 borderline episodes sent to review; both cameras audited |
| `sreetz-nv/so101_teleop_vials_rack_left` (partial copy) | v3.0 | 75 | **44 / F** | Partial copy (166 MB, one of the two declared cameras): audit flagged **incomplete** — that camera's files are absent from this copy; the upstream dataset may differ |

On a defect-injection suite built by the RoboAudit authors (43 known defects
planted across both formats — a home-field test, so read it as such),
RoboAudit detected **43/43** with **0 false positives** on 40 clean synthetic episodes. The
comparable open-source tool RDA (Robot Data Audit, PyPI) reached a verdict
on 22 of the same 43 (15 exclude + 7 unverifiable), recorded 2 more as
findings only, and the remaining 19 fell outside its check set — it
implements no checks for action-state jumps, instruction problems,
episode boundaries, and similar defect types. On real
data, RDA's conservative all-pass behaviour was the more cautious one;
RoboAudit's own early exclusions on real data were themselves borderline,
which is exactly why the `review` disposition now exists.

## Limitations — read this before trusting a score

- **The score is a relative indicator, not an absolute quality measure.**
  It compares well inside one dataset or across versions of the same
  dataset. A 44/F dataset may simply be a teleoperation recording with
  frequent discontinuities, not "bad data".
- **No guarantee about training outcomes or robot safety.** RoboAudit
  checks structural and statistical properties of data. It does not prove
  that training on the kept episodes will perform better, and an A2
  "review" verdict explicitly means the tool *cannot* distinguish a
  recording defect from a robot's normal operating characteristics.
- **Disposition thresholds are working values, not yet validated at
  scale.** The borderline margin (1.5×) was calibrated on synthetic
  injections plus three real datasets (175 episodes). Sensitivity was
  measured on those datasets, not assumed: varying the A1 boundary
  constant (0.15–0.35) changed no disposition at all, and the
  injected-defect dispositions were identical at margins 1.5 and 1.7 —
  but borderline episodes do move with the margin (at 1.3, two battery
  episodes would flip from review to exclude and sreetz exclusions
  would rise from 7 to 11; at 1.7, sreetz exclusions would fall to 4).
  Treat the constants as working values, not constants of nature.
- **Sampling mode is approximate.** Boundary-case frozen segments can be
  missed; use a full audit for a final verdict.
- One representative set of statistics is computed per declared camera;
  every declared camera *is* decoded and checked, but cross-camera
  synchronisation is not yet measured.

## Troubleshooting

- **Exit code 2 — the error says `meta/info.json` is missing.** You
  pointed the command at the wrong folder. Pass the dataset root (the
  folder containing `meta/info.json`), not a parent or child folder,
  and make sure the dataset is downloaded locally first — RoboAudit
  reads local folders only.
- **Exit code 2 — `--out` refused.** The output folder must be outside
  the dataset folder. This is deliberate: it makes it impossible to
  write audit output into the original data.
- **Exit code 3 — incomplete audit.** One or more checks ran partially
  or errored; `report.html` and `result.json` say which and why. The
  usual causes are missing files or videos that failed to decode. All
  four outputs are still written, but read the incomplete-audit note
  in [Score and dispositions](#score-and-dispositions) before using
  the indexes.
- **Videos fail to decode.** RoboAudit decodes with OpenCV first and
  falls back to a system `ffmpeg` binary when one is on your `PATH`
  (needed for codecs OpenCV cannot read, e.g. AV1). If many episodes
  fail to decode, install ffmpeg (e.g. `apt install ffmpeg` or
  `brew install ffmpeg`) and re-run. The per-camera decode statistics
  in the report show how many episodes each path read.

## License

MIT — see [LICENSE](LICENSE).

---

## 한국어 요약

**학습시키기 전에, 감사부터.** RoboAudit는 LeRobot 로봇 데이터셋의
건강검진 도구입니다. 데이터셋 폴더를 넣으면 100점 만점 점수와 등급,
결함 목록, 그리고 에피소드별 처분(제외/보류/유지)을 돌려줍니다.

핵심 3가지:

1. **심어 둔 고장 43개 전부 검출** — 비슷한 공개 감사 도구는 판정까지
   간 것이 22개였습니다. (단, 시험장은 RoboAudit 제작진이 만든 것이라
   홈그라운드 시험으로 읽어 주세요. 근거는 위 영문 비교 섹션.)
2. **구 포맷 v2.1도 변환 없이 직접 감사** — LeRobot 0.7.0 기준 공식
   로더가 로딩을 거부하는(BackwardCompatibilityError) 형식입니다.
3. **점수만이 아니라** 제외/보류/유지 에피소드 목록까지 나와 학습에
   쓸 에피소드를 고를 수 있습니다.

실제 공개 데이터셋 성적표 (전부 실측):

| 데이터셋 | 형식 | 점수 | 제외/보류 | 한 줄 소견 |
|---|---|---|---|---|
| `lerobot/aloha_sim_transfer_cube_scripted` | v3.0 | **79 / C** | 0 / 2 | 범위 경계를 살짝 넘은 2건은 자동 제외가 아니라 사람 확인(보류)으로 |
| `00ri/so100_battery` | v2.1 | **84 / B** | 0 / 5 | 흔들림으로 잡힌 5건이 실제로는 동작 많은 에피소드로 보여 전부 보류; 카메라 2대 모두 감사 |
| `sreetz-nv/so101_teleop_vials_rack_left` (부분 복사본) | v3.0 | **44 / F** | 7 / 8 | 부분 복사본(166MB, 선언된 카메라 2대 중 1대만 다운로드)으로 감사 — 없는 카메라는 이 복사본의 속성이고 원본 데이터셋은 완전할 수 있음; "불완전한 감사"로 명시; 점프 15건은 측정 강도로 제외/보류 분리 |

- v2.1·v3.0 형식을 자체 파서로 직접 읽습니다 (LeRobot 0.7.0 기준 공식
  로더가 거부하는 v2.1도 변환 없이 읽음).
- 검사는 규칙+임계값 12종뿐이라 감점 이유를 전부 설명할 수 있고, 원본
  데이터는 읽기만 하며 절대 수정하지 않습니다.
- 애매한 에피소드는 자동으로 버리지 않고 `review_index.json`으로 분리해
  사람이 확인하게 합니다. 검사가 일부라도 실패하면 "불완전한 감사"라고
  성적표와 종료 코드(3)로 명시합니다.
- 종료 코드 0은 "감사가 전체 범위까지 끝까지 돌았다"는 뜻일 뿐,
  데이터셋이 "합격"했다는 뜻이 아닙니다. 불완전한 감사에서도
  `clean_index.json`은 나오지만, 그 유지 목록은 "돌릴 수 있었던
  검사에서 발견이 없었다"는 뜻으로 읽어야 합니다.
- 제외된 에피소드는 유지 목록(`clean_episodes`)에도 보류 목록에도
  들어가지 않고, `clean_index.json`의 `excluded_episodes` 항목과
  `result.json`에 걸린 검사 코드와 함께 기록됩니다. 보류 에피소드도
  유지 목록에는 들어가지 않습니다.
- 타임스탬프가 `frame_index / fps`로 합성된 격자형인지도 진단해
  리포트와 `result.json`에 표시합니다 (성적표 데이터셋 3개가 모두
  격자형이었습니다). 진단은 시계 출처와 간격 규칙성의 두 축으로
  표시하고, `frame_index` 자체의 빈틈은 "기록 후 삭제"를 뜻하는
  별도 신호로 보고합니다(시계가 아니므로 간격 비율 증거를 만들지
  않습니다). A2 점프 발견에는 실제 타임스탬프일 때만 간격
  비율 증거가 붙고, 실제 관절(state)이 명령을 따라갔는지도 증거로
  기록됩니다. 점수와 처분은 이 증거들로 바뀌지 않습니다.
- 라이선스는 MIT입니다.
- 점수는 절대 품질이 아니라 상대 지표입니다. 학습 성능이나 로봇 안전성을
  보증하지 않으며, 처분 기준값(경계 1.5배)은 아직 잠정값입니다.

설치와 사용법은 위 영문 섹션을 따르세요: `pip install roboaudit`로
설치한 뒤 `roboaudit <데이터셋 폴더> --out <출력 폴더>` (또는 저장소를
clone해 `pip install .`로 설치).

**사례 공유 (선택 참여, 기본 꺼짐)**: 처분 기준값(경계 1.5배 등)은 아직
잠정값이라, 여러 실제 데이터셋의 감사 사례가 쌓여야 검증할 수 있습니다.
`roboaudit share <result.json>` 또는 감사 시 `--share-bundle`을 명시한
경우에만 요약 파일(`share_bundle.json`)이 만들어집니다. 자동
전송은 절대 없으며, 제출은 본인이 GitHub 이슈에 직접 붙이는 수동
행동입니다. 요약에는 버전·형식·개수·점수·검사별 발견 건수와 margin
분포·처분 집계만 들어가고, 데이터셋 이름·경로·파일명·과제 원문(해시
포함)·원본 측정값·카메라 키 이름은 화이트리스트 방식이라 구조적으로
들어갈 수 없습니다. bundle 안의 빈 판정 칸에 직접 확인한 에피소드의
오탐 여부를 적어 제출하면, 사람이 판정한 사례가 쌓여 기준값 검증의
재료가 됩니다.
