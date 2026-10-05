# Media knowledge: who is who, who speaks, and what happens

An analysis takes an episode or a film apart without dubbing it. It never translates, clones a voice or generates speech. Everything it learns is tied to the file's **content**, not to its name.

## Identity

| Thing | What identifies it |
|---|---|
| Series | A library provider id (`show:tvdb:…`, `movie:tmdb:…`), or a local id bound to the show folder's full path. A folder *name* never decides it. |
| Episode or film | Provider ids when known, else its content. |
| Source revision | Sampled hash, size, duration and stream layout of one file. The same file copied elsewhere is the same revision. A re-encode or another cut is a new revision of the same episode. |
| Character | Belongs to one series. It keeps its id through renames, aliases, merges and variants (an age, a transformation, an edition). |

A voice group (`SPEAKER_03`) is only an identity inside one revision. Naming a group links it to a character of the series. Older releases kept names under file and folder names. Under **Analysis → What has been analysed → Move older names onto this episode** you preview and apply that move. Ambiguous cases (two files with one name, two shows filed under one folder name) are left alone. A suspected match between a local series and a provider series is only applied when you confirm it.

## What an analysis records

Each stage is recorded against the source revision, separately:

- **Audio:** lines, voice groups, levels, speaker baselines, pitch and original words, energy curves (`line-features/1`, true sample RMS in `dBFS-rms-sample`), and what the series learns about each voice.
- **Picture (optional):** shots, faces, face tracks, mouth movement, who appears to speak, and scenes.
- **Knowledge (optional):** title knowledge proposals.

A stage is *done*, *needs a rerun* (something it depends on changed), *failed*, *not supported here*, *off* or *not run*. Regrouping voices makes the speaker baselines stale, but not the energy curves. **Rerun** reuses earlier stages and runs only what changed.

The energy curves are a different measurement from the level analysis. `levels` reports `dBFS-rms-speech`, the RMS of 20 ms frame peaks. On a real episode the two correlate at 0.94 and differ by about 9.5 dB, so the units are never mixed.

## Published cast (optional)

A published anime already has a public cast list. `doblarr cast` links a series to its AniList entry so the characters come with their role, gender, description and original voice actors:

```
doblarr cast series                         # series ids and titles
doblarr cast search show:tvdb:123           # sends the title to anilist.co; stores nothing
doblarr cast link show:tvdb:123 URL [--season N]
doblarr cast show show:tvdb:123 --episode 4 # main cast + guests described in episode 4
doblarr cast import show:tvdb:123 [--roles MAIN,SUPPORTING]
```

The title is the only thing sent, and only when you search. A link is your choice of entry, stored apart from what episodes taught, like other library metadata. A show's search lists TV entries before its films. Catalogues list each season as its own title, so a link can be per season.

**Import** never renames or overwrites a character. A character you already have matches a cast member by name, alias or a unique part of the name, with romanization folded (`Hyūga`, `Hyuuga` and `Hyuga` are one name). It gains the published facts and the published name as an alias. A name part shared by several cast members creates nothing and is reported for you to settle. Only characters that existed before the import can match.

Other catalogues (Anime News Network, MyAnimeList through Jikan, Bangumi) can be linked next to AniList, so a character's dub voices in other languages come with their sources. See [title research](title-research.md).

## Title research (optional)

With `research.enabled` on, a title's Research tab (or `doblarr research`, `doblarr scripts`, `doblarr titles`) asks the web cited questions, looks for transcripts and screenplays, and gathers the title's ids in other catalogues. Only the title or your question is sent. Everything it finds waits for review: answers become external notes, terms become proposed show-scoped entries, dub voices become cast leads, and scripts are read by an analysis only when `analysis.use_reference_scripts` is on. Details: [title-research.md](title-research.md).

## Who speaks

Every line keeps how its voice was decided:

- heard and grouped (with the margin over the next voice);
- a small group folded into a larger voice;
- too short to group, joined the closest voice;
- no usable voice, took the previous speaker.

Weak decisions are marked `?`. Lines you assign by hand are kept through every regroup. Select several lines to split a group into the two people it holds. After any change the speaker baselines are recomputed from the raw measurements; nothing is re-measured.

Other audio tracks (dubs) help tell voices apart only when they are permitted (`speakers.tracks`) **and** line up with the original. Each track is aligned against the original mix in six windows. A track from another edit, a commentary or audio-description track, or a studio evaluation track is not used, and the page says why.

Suggested names for unnamed groups come from the series' voice memory, kept per voice model and source language. Each suggestion shows the margin to the next character; a small margin is a weak suggestion.

## Picture evidence (optional)

Install the extra (`pip install "doblarr[vision]"`) and download the model files through **Settings** or `POST /api/vision/models/{id}/download`. They are checked against their checksums. Live action uses YuNet and SFace. Animation uses an anime face cascade and DINOv2 crops from the local model cache.

A face track is the same face across a few frames. Naming one keeps that face as an approved reference for the series. Other tracks are then *proposed* as that character, never named on their own.

Mouth movement is compared with each line's speech energy. It is weak evidence: on the reference anime episode it barely correlated, and on a low-resolution live-action sample only slightly better. A face that is visible but not speaking never takes a line. With nobody on screen, a line is *offscreen*; without picture analysis it is *not analysed*.

## Title knowledge

Under **Analysis → Extract title knowledge**, a language model reads the lines in bounded windows. It is told to use only what the lines say. It proposes characters, aliases, relationships, events, locations, scene intent, addressees, behaviour and terms, each citing its lines.

Under **Knowledge → Title knowledge** you accept, correct, reject or defer each proposal, then **Activate** a revision. Nothing is used before activation.

- A job freezes the revision it starts with.
- An episode only sees knowledge from itself and earlier episodes, never from later ones and never from held-out evaluation episodes.
- A reveal can be held back until a later episode.
- Contradicting accepted claims are kept and marked, and neither is used until you retire one.
- Your corrections survive later extractions.
- Library metadata is shown apart and is not evidence from the episode.

Accepted knowledge reaches translation as reviewed background. It ranks above the machine synopsis; the glossary still decides wording. It also reaches acting: a character's standing direction and accepted behaviour form their direction layer.
