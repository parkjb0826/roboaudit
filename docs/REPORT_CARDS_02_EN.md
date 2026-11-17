# Report Cards #02 — Ten public LeRobot datasets, audited: every timestamp is a grid

*The second in a series: we run RoboAudit on public LeRobot datasets and
publish the report cards, including the parts where the tool itself is
wrong — one card in this issue is exactly that. Scores are relative
indicators, not absolute quality measures — and nothing here says
anything about how well a policy trained on the kept episodes will
perform.*

Tool: RoboAudit 0.3.0 · 12 rule/threshold checks · full audit (no sampling).
The xarm card was re-audited with RoboAudit 0.3.1 after a reader bug was
found and fixed — see its card.

Repository: https://github.com/parkjb0826/roboaudit

*Thanks first: the timestamp diagnostic used throughout this issue
exists because of a question in the #01 thread — nootxlm asked whether
the abrupt-jump findings could be separated by the frame interval
across each jump. Testing that idea showed the intervals carry no
information in the first place, and 0.3.0 measures and reports that
directly. (0.3.1 has since split the diagnostic into two independent
axes — clock provenance and interval regularity — and reports gaps in
`frame_index` itself as a separate signal; the verdicts in this issue
are stated in those terms.) This issue is the follow-up: how far does
it go?*

*Calibration note: the three #01 datasets were used to calibrate the
disposition thresholds, so their grades are in-sample. The seven new
datasets in this issue were not part of that calibration.*

---

## The headline: 10 of 10

Report Cards #01 audited three datasets, and all three turned out to
have synthetic timestamps — the timestamp column is `frame_index / fps`
by construction, not a capture clock. This issue widens the sample
with seven more public datasets. The result did not soften:

| Dataset | Format | Episodes | Score | Keep / Review / Exclude | Timestamps |
|---|---|---|---|---|---|
| `Bapt120/so101_cup7` | v2.1 | 2 | **89 / B** | 1 / 0 / 1 | grid |
| `MarkoBrie/so101_banana` | v2.1 | 2 | **89 / B** | 1 / 0 / 1 | grid |
| `lerobot/aloha_sim_insertion_human` | v3.0 | 50 | **89 / B** | 49 / 1 / 0 | grid |
| `lerobot/aloha_sim_transfer_cube_human` | v3.0 | 50 | **69 / D** | 47 / 3 / 0 | grid |
| `lerobot/aloha_static_cups_open` | v3.0 | 50 | **89 / B** | 49 / 1 / 0 | grid |
| `lerobot/pusht` | v3.0 | 206 | **82 / B** | 200 / 6 / 0 | grid |
| `lerobot/xarm_lift_medium` | v3.0 | 800 | **80 / B** * | 796 / 4 / 0 | grid |
| `lerobot/aloha_sim_transfer_cube_scripted` (#01) | v3.0 | 50 | **79 / C** | 48 / 2 / 0 | grid |
| `00ri/so100_battery` (#01) | v2.1 | 50 | **84 / B** | 45 / 5 / 0 | grid |
| `sreetz-nv/so101_teleop_vials_rack_left` (#01) | v3.0 | 75 | **44 / F** | 60 / 8 / 7 | grid |

\* The xarm row is the corrected grade from the 0.3.1 re-audit. Under
0.3.0 it read **0 / F** — for reasons that were ours, not the
dataset's. Read its card before quoting either number. The sreetz row
is #01's audit of a partial copy (one of two declared cameras absent
from the copy) — see #01 for that card.

"Grid" is measured, not eyeballed: for every episode, the largest
deviation between the timestamp column and `frame_index / fps` sits
between 5.6×10⁻⁸ and 8.9×10⁻⁷ seconds — float rounding, nothing more —
and not one of the intervals checked deviates from `1 / fps` by more
than a millisecond. In the two-axis terms 0.3.1 now reports: all ten
read clock provenance `synthetic_grid`, interval regularity `uniform`,
and none of the ten has a single gap in `frame_index`.

## What a grid clock means — and what it does not

If you train policies on these datasets, mostly nothing: the frames,
states and actions are all there, in order. Grid timestamps are how
the recording stack writes time, not a defect in the data.

But anything that treats the timestamp column as *evidence about
capture* is blind on every dataset above:

- **Dropped frames are invisible.** If the recorder dropped frames and
  the writer re-indexed, the file's timing cannot show it — every
  interval is exactly `1 / fps`, whether frames were lost or not.
- **Timing-based analysis has nothing to measure.** Latency estimates,
  camera/sensor synchronisation checks, and interval-based drop
  detectors (including the one suggested in the #01 thread) all
  silently degenerate to "everything is nominal".
- **The reverse inference is also unavailable.** A perfect grid does
  not prove capture was clean; it proves the writer synthesised the
  column. The file simply does not record what happened on the clock.

The honest limits, stated plainly: ten datasets is a small,
convenience-chosen sample — six official `lerobot/` datasets and four
community ones, three simulated and seven real, spanning ALOHA,
SO-100/SO-101, PushT and XArm. All of them passed through LeRobot
tooling, so this is a finding about that ecosystem's writer defaults,
not about robot data in general. A dataset whose recorder wrote real
capture timestamps and preserved them through conversion would break
the streak. We have not found one yet — see the request at the end.

## The cards

### `lerobot/aloha_sim_transfer_cube_human` — **69 / D**

The human-demonstration counterpart to #01's scripted set, same task.
Three A1 range excursions (episodes 2, 39, 48) instead of the scripted
set's two — that is the whole difference between 69/D and 79/C. All
three sit just past the dataset's own range band (margins 0.011 to
1.111, none near the 1.5 exclusion line), so all three are review, not
exclude. Human demonstrations being slightly less tidy than a script
is not a surprise; the tool's job is to point at the episodes, and it
does.

### `lerobot/pusht` — **82 / B**

Nothing excluded. The deductions are four V3 episode-length outliers
(49, 56, 60 and 246 frames against a median of 122) and two A2 jump
warnings — all review-grade. PushT episodes genuinely vary in length;
a short push is not a defect, and the report says "look at these"
rather than pretending otherwise. Worth noting that PushT's timestamps
are a grid at 10 fps like everyone else's: variable episode lengths,
perfectly regular intervals.

### Four more at **89 / B** — and two caveats about tiny datasets

`lerobot/aloha_sim_insertion_human`, `lerobot/aloha_static_cups_open`,
`Bapt120/so101_cup7` and `MarkoBrie/so101_banana` all land on the same
deduction shape: one A1 excursion (−10) and the standing L2 note for
missing success/failure labels (−1). In the two ALOHA sets the
excursions are marginal (0.187 and 0.414) and go to review.
`aloha_static_cups_open` is also the batch's only real-robot
multi-camera set: four cameras, 20,000 frames, no video findings.

The two SO-101 sets need a caveat in the other direction. Each has
only **2 episodes**, and in each, one episode is *excluded* by an A1
finding with a very large margin (76.4× and 58.3×). But with two
episodes, the range band is built from the single other episode, so
"out of range" means little more than "unlike the other one". The
margins are large; the evidence base is tiny. Both readings belong on
the card, so here they are.

### `lerobot/xarm_lift_medium` — **80 / B**, corrected (under 0.3.0 it read 0 / F — and the F was ours)

This is the card where the tool was wrong, in print, on the record.

The 0.3.0 audit reported 435 of 800 episodes with a video frame count
of 26 against a declared length of 25 — a warning each, −1,305 points,
435 exclusions, score floored at 0. Before publishing that as a
dataset defect, we checked it three ways:

1. The episodes all live in one shared video file. It contains
   **exactly 20,000 frames** — 800 × 25. There is no extra frame.
2. Every episode's declared video span in the metadata is exactly
   25 frames, and every episode has exactly 25 data rows.
3. RoboAudit 0.3.0 decoded episode segments from large shared files
   with an ffmpeg `-ss`/`-t` window, with the duration rounded to
   milliseconds. A 25-frame segment at 15 fps is 1.6667 s; rounded to
   1.667, the window also admits the frame at the boundary — the next
   episode's first frame. Running the reader's exact command by hand
   reproduced the pattern precisely: 26 frames for episode 0
   (flagged), 25 for episode 1 (not flagged).

Checking further — a pixel-level comparison against one full
sequential decode of the file — showed the rounded window had two
more failure shapes the count check never sees: episodes whose start
rounded *up* decoded **25 frames shifted by one** (right count, wrong
frames, no finding ever fired), and the last episode decoded 24.
Three failure shapes in all: one frame too many, one too few, and a
silent one-frame shift.

So the +1 frame was produced by our decoding, not stored in the
dataset. **The 435 exclusions and the 0/F were not a judgement of
`lerobot/xarm_lift_medium`, and we do not stand behind them.**

The fix shipped in 0.3.1: segments are now decoded frame-exactly —
seek to half a frame before the segment start, then cap the output at
the declared frame count (`-frames:v N`). Verified pixel-identical
(max difference 0.0) to the full-decode slices at the first, middle,
and last episodes, at unchanged audit speed. Re-audited with the
corrected reader, the dataset's real profile is minor: one A1 range
excursion (episode 691, −10), three V2 video-stability warnings
(episodes 245, 419, 499, −9), and the standing L2 note (−1) — **80 / B,
796 keep / 4 review / 0 exclude**. (One V2 episode differs from the
0.3.0 reading — 245 instead of 83; both sit within about a unit of
the shake bar, and both flip with exact decoding, 83's own median
falling once the borrowed boundary frame is gone and 245 crossing
because the dataset median it is compared against drops.)

The other nine datasets in this issue were re-audited under 0.3.1
too: **scores and dispositions identical, every one.** The bug needed
a segment duration whose millisecond rounding crosses a frame
boundary — 25 frames at 15 fps is the unlucky geometry; the ALOHA
sets' 400-frame segments at 30 fps round down, and PushT's 10 fps
durations are exact in milliseconds — which is why it hid until an
800-episode 15 fps dataset was audited.

If there is a lesson in this issue, it is this one: an audit tool's
findings are claims, and claims get checked — including, especially,
the dramatic ones.

## What we are looking for

- **A public LeRobot dataset with real capture timestamps.** The
  interval-ratio evidence shipped in 0.3.0 has still never fired on
  real data, because every dataset we have audited synthesises its
  clock. If yours preserves real timing — recorded outside the
  standard writer path, or with hardware timestamps intact — it would
  be the first, and we would like to audit it.
- **Your audit cases.** If you ran RoboAudit on your own dataset and
  want to share the case (opt-in; the shared bundle is a
  whitelist-extracted summary, not your data), the issue template in
  the repository is the way in. Cases where the tool is wrong are the
  most valuable ones — the xarm card above is why.

**Next in the series:** the search for a dataset whose clock is real —
and the harder A2 tests this series keeps promising itself: deletion
points chosen blind (onset, reversal, gripper contact, slow stretches,
single frames), with the full denominator published.
