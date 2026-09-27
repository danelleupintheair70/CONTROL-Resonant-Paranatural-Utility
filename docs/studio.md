# Episode studio

The studio is one persistent workspace for one episode (or movie). It sits on
top of the things Doblarr already has — the job queue, each run's review
snapshot, the reviewer-decisions sidecar, saved versions — and adds only what
had no home: which track or transcript plays which role, how two releases line
up, what an experiment was allowed to read, what a listener marked and decided.

Open it from **Dubs** (the *Studio* button on a run) or from an episode or movie
page (**Open studio**). The address is `/studio/<session>/<view>`; the view,
line, listening window and playback position are saved on the server, so a
reload or another browser lands in the same place.

## Views

| View | What you do there |
| --- | --- |
| Overview | Pick the working style and checkpoints, request budgets, the output region and the reference policy. Declare references and their roles, align them, import earlier experiments, render a draft. |
| Cast | See who speaks with which voice and where that choice came from (series, episode, line). Audition a character on fixed lines and cast the winner, for one episode or the series. |
| Dialogue | The existing review editor, mounted inline: wording, timing, voice, delivery, takes, findings. The transport follows the line you are on. |
| Compare | Play the original, the dub, delivered tracks, saved versions and references over the same window; loop a line; play a line in every version; blind labels; notes pinned to time; window verdicts; imported comparisons; writing experiments. |
| Export | Exactly what the chosen version contains, which lines are stale, which findings are open — then export without surprise speech. |

### Transport and keys

One audio element plays at a time; a small silent H.264 proxy of the scene
follows it (original releases are often HEVC/Matroska, which browsers cannot
play). Switching source keeps the moment on the target timeline; a reference is
cut through its alignment's time map, and a stretch the reference does not have
(a cut) is refused rather than guessed.

`space` play/pause · `0`/`O` original · `1`–`9` versions · `R` reference ·
`J`/`K` previous/next line · `L` loop the line · `P` play the line in each version ·
`M` level-matched preview · `N` mark this moment.

*Level-matched preview* only changes the playback volume so two sources can be
compared at the same speech level. It never changes the render, and it is
labelled that way.

## Working styles

- **Automatic** runs within the budgets shown and saves a result with every
  unresolved finding listed.
- **Guided** stops at the checkpoints you choose: casting before the first
  draft, script review before export, the final export.
- **Manual** never queues anything you did not ask for.

Switching style changes when the studio asks you, never what is stored.

## References and roles

A track's language tag says what the release claims, not what it contains. A
reference records its media, stream, edition, language, how its text was
obtained (speech recognition, a subtitle stream, the run's own cues, pasted
lines) and an explicit set of roles:

| Role | Meaning |
| --- | --- |
| meaning | The original dialogue: facts, relationships, intent. |
| adaptation | Another localisation's writing, e.g. the English dub transcript. |
| performance | A track to hear for delivery. |
| voice | A sample for voice identity (cloning). |
| evaluation | Held out from every generation request; revealed separately. |

An evaluation-only reference cannot hold any other role, its text is never
served to the browser outside an evaluation session, and its audio is not
offered as a playback source. A dub transcript (what another cast said) and
subtitles that translate the original are different text kinds.

**Transcribe windows** runs local speech recognition over bounded windows of a
track (at most 240 s each) through the ordinary job queue.

## Alignment

Releases rarely share a clock. An alignment keeps each reference on its own
timeline and maps it onto the original with a piecewise time map (offset, rate,
confidence per segment), estimated from the audio or entered by hand. Lines are
grouped many-to-many (one dub merges two lines, another splits one). Every
group is `matched`, `uncertain`, `unmatched` or `excluded`; only matched groups
are ever sent to a writer. Excluding, including, unlinking and relinking are
new alignment revisions.

## Reference policy

`translate.reference_policy` (set from the studio's Writing direction):

- **original_only** — no reference is sent. The default, and what every
  existing configuration does.
- **reference_suggestions** — the original decides facts, relationships, plot
  and intent; the aligned reference may lend phrasing, idioms or wordplay that
  keeps them. The long-standing "invent no new jokes" rule still holds for
  anything the model invents; a joke taken from the supplied adaptation is
  allowed only when it contradicts nothing in the original.
- **follow_edition** — target a chosen adaptation's choices while keeping the
  original's facts; departures are recorded.

A render with a policy other than *original only* builds an aligned-reference
file from the chosen alignment revision and keys its script cache on that
file's content, so an alignment or policy edit re-translates and a moved file
does not.

## Holdout boundary

Evaluation-only text is fingerprinted (word and character n-grams; short lines
whole). A guard wraps the translation driver, so **every** request — first
attempt, invalid-reply retry, prep pass, shortening repair, resume — is scanned
before it leaves the process. A match blocks the request and names only the
label, never the matched text. The pipeline's own generated Spanish may be read
back even when it happens to match. Lines too short to fingerprint are counted
in the manifest rather than claimed as checked.

Set evaluation references under **Writing direction → Held out from
generation**; a render then carries `translate.holdout_files`.

## Writing experiments

In **Compare → Writing experiments**:

- **A** writes from the original only, **B** from the English dub transcript
  only (a diagnostic of what an intermediary changes), **C** from both.
- The unit of comparison is an alignment group; every condition writes for the
  same slots (speaker, duration, character budget). B gets the slots' timing,
  never their Japanese text.
- A definition is frozen when created: excerpts and decision criteria are
  declared before any result exists; the alignment revision, model, sampling,
  locale, policy, shared scene notes and budget are pinned. A changed definition
  is a new experiment.
- Shared scene notes are checked for any condition's dialogue and for the
  held-out adaptation before anything runs.
- Translation memory is off by default; when on, candidates matching held-out
  content are dropped and counted.
- Each excerpt is checkpointed under the experiment's own namespace; resume
  reuses a checkpoint only if its input manifest matches exactly.
- A finished variant is frozen. Its manifest lists what it read and what it
  never read, with no held-out content in it.

**Judge blind** creates an evaluation session with numbered labels (never the
condition letters). Judgments are per unit and dimension — source meaning,
character, regional naturalness, humor, fit to the picture, timing,
preference — with *same*, *neither*, *uncertain* and *n/a* as real answers,
plus critical meaning errors. Revealing the labels, and separately the
official adaptation, is logged. A correction is a new revision; after the
official adaptation is revealed every correction is marked **assisted** and the
clean result stays as it was. The summary reports counts and a pilot gate
stated as what was observed; a handful of excerpts cannot establish general
superiority or statistical significance, and source fidelity needs a reviewer
who reads the source language.

A frozen variant can be spoken through a finished run's cast and processing
(**Speak it**), which queues only those lines. That run's cues must be the
experiment's meaning source.

## Auditions and casting

An audition picks one character's lines from a finished run by what the
original actor did (quiet, intense, calm — from the run's source measurements
— and lines in an exchange) and lets several candidates say exactly those
lines: the current voice, a preset, a directed preset, a clone of the original
actor, or (experimental) a clone from each line's own audio. A performance type
the material lacks is reported as missing. A direction an engine cannot take is
reported as unsupported, not dropped. Clone references come from the
original-language separated dialogue, with their duration, overlapping
speakers and level over the bed as findings; evaluation-only tracks are
refused. Auditions run through the queue with a candidate and request budget,
can be cancelled, and resume paying only for missing takes.

Casting has scope: a series choice is inherited by every episode without its
own; an episode can override a character; a line can override its episode.
**Who follows this** lists which episodes would take a new series choice and
which keep their own before you change it. *Cast and re-render only X* writes
the run's voice cast (the one the synthesizer reads) and queues only that
character's lines.

## Importing earlier experiments

**Overview → Import an earlier experiment** reads a comparison manifest or a
voice-audition record from the work folder, shows what exists and what is
missing, and requires you to map every legacy speaker and source track before
it records anything. Nothing is generated, moved or re-rendered; importing the
same file again changes nothing. A manifest does not contain listening
judgments — the old page kept them in browser storage — so only an exported
results file can bring them in (**Import exported results**). Settings the old
experiment compared stay attached to it and never become product defaults.

## Export

Export uses the selected take of every line. With no pending choice it hands
over the saved version and renders nothing. Choosing different existing takes
re-mixes them without generating speech; if a pending edit would generate new
speech, export refuses until you confirm. A line whose wording changed after its
take was made is stale and is never exported as if it said the new words. The
original media and earlier versions are not touched, and publishing to a
library is a separate step.
