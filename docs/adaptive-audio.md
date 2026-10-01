# Voice envelopes and background policies

An envelope shapes a dubbed line's loudness *inside* the line: an early emphasis, a rise, a trailing finish, an intentional cutoff. A background policy decides how the music and effects make room for the dialogue. Both reprocess audio that already exists. **Neither ever generates speech.** Changing a template or its strength reprocesses the existing take and remixes. Changing the background policy only remixes.

## Turning it on

```yaml
levels:
  mode: consistent            # envelopes render inside the post-fit level owner
adaptive:
  mode: suggest               # off | suggest | apply
  judge: retrieval            # retrieval | kev/<model> | laya/<model> | llm:<prompture model>
  background_policy: ""       # e.g. background/strong-ducking; "" keeps sidechain ducking
```

| Mode | Behaviour |
|---|---|
| `off` | Renders exactly what earlier releases rendered. |
| `suggest` | Records a recommendation per line for review. |
| `apply` | Renders the recommendations. |

A choice you make by hand in review always applies. Envelopes render in the same pass as the post-fit level owner, so `levels.mode: legacy` reports them as *not supported here* rather than adding a second loudness stage.

## Templates are data

**Knowledge → Audio templates** lists the catalogue: 13 voice envelopes, 8 background policies and 3 presets.

- A template is a definition: anchors on the line's speech (0 = first word, 1 = last word) in relative dB, interpolation, smoothing, parameter bounds, valid durations, required evidence and contraindications.
- Adding a curve is a data change: save it and it is offered, previewed, retrieved and rendered like the built-in ones.
- Every save is a new version. A saved dub keeps the version it used.
- Templates import and export as bundles; an invalid bundle imports nothing.
- `0.5` linear gain is about −6 dB. It is a gain, never a target.

## How a line gets its envelope

1. The original actor's line and the generated, time-fitted take are measured.
2. **Retrieval** first drops templates that cannot apply: wrong length, too little speech, contraindicated (a trailing line does not get a late emphasis), discouraged for the character. It then ranks the rest by how well each matches the original's shape, compared with a bounded warp so a translated line of a different length is not forced syllable to syllable. It also weighs the line's tags, the character's preferences and approved examples. *Preserve* is always a candidate.
3. A **judge** picks from a bounded packet of evidence:
   - *Retrieval* is a rule and is recorded as one.
   - `kev/*` and `laya/*` use typed decision models.
   - `llm:*` asks a language model for a validated JSON answer.

   Answers that name something outside the packet, provider failures and abstentions fall back to a recorded conservative choice. A model's score is stored as uncalibrated.
4. The template is **fitted to the take**: its own speech span, pauses and stresses. If the take already has the shape, the strength is reduced by that much.
5. It renders in one pass with the level gain, under the peak ceiling.

## Background policies

A policy plans one gain curve for the whole programme from the lines' actual speech. It:

- stays down through short hesitations and recovers in real pauses;
- moves at the attack and release you set, so it does not pump;
- steps aside for impacts in the bed (transient protection);
- can swell after a scene's last line and ease across scene changes;
- never dips deeper than `max_bed_attenuation_db`.

With a policy active the mix is flat and the sidechain compressor is bypassed. Two ducking systems never compound.

## Reviewing

In review, each line's **Voice envelope** panel shows:

- the choice, who made it, and what the render actually did (strength, share already in the take, range, peak);
- the candidates and why each was offered;
- the same take five ways: as generated, with the envelope, level-matched (labelled, so it cannot hide the volume change), the original, and in the mix.

From the panel you can pick another template or strength, keep the take as generated, or undo your choice. Each queues a rerender that reuses the takes.

Marking a result *Good* can make it an example for similar lines. *Not right* records what was wrong (envelope, level, acting, timing, background, wrong speaker). Examples can be retired at any time; dubs already made stay reproducible.

A held-out evaluation episode never becomes an example, never feeds retrieval, speaker memory or title knowledge, and taking it out of the held-out set is recorded.

## What has and has not been validated

| Check | Result |
|---|---|
| DSP on 126 renders of 63 real generated takes | Formats preserved, re-renders byte-identical, peaks under the ceiling. |
| Template or strength change | Measured as zero new speech requests. |
| Preserve / off | Measured as the previous render path, byte for byte. |
| Local language-model judge | Valid answers on 61 of 63 lines. It mostly kept takes as generated. |
| Judge-assisted vs. retrieval-only, by ear | **Not validated:** no listening test has been done. The comparison page under `work/benchmarks/adaptive-audio/` is ready for one. |
