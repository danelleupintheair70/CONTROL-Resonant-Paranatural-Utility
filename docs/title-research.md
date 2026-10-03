# Title research

Doblarr can look a title up in public sources: who voices each character in
each dub, how a dub says the names and terms, and transcripts or screenplays
other people wrote. Coverage depends on the title. Most titles appear in a few
sources and are missing from the rest, so every lookup is cheap and quiet when
it finds nothing.

## Rules

- **Off by default.** `research.enabled` gates every API route and UI action
  that sends something out. The CLI runs only when you type the command.
- **Only the title, an id or your question leaves the machine**, and only when
  you ask. Episode audio, subtitles and file names stay local.
- **Nothing found applies itself.** A cast link is your choice. Cast leads wait
  for you to accept them. Research answers become `proposed` external notes.
  Terms become show- or film-scoped `proposed` knowledge entries, which the
  resolver ignores until someone reviews them. Reference scripts are read by an
  analysis only when `analysis.use_reference_scripts` is on.
- **Queued jobs are unaffected.** A job keeps the knowledge and narrative
  revision it froze; research never edits those.

## Settings

```yaml
research:
  enabled: false
  model: ""                  # Prompture model; blank uses analysis.knowledge_model
  depth: quick               # quick | standard | deep
  max_cost_usd: 1.0          # cap on model spend per question
  cache_days: 30             # how long catalogue answers are reused
  opensubtitles_api_key: ""  # optional
  tmdb_api_key: ""           # optional
  kitsunekko_mirror: ""      # path to a local clone of a Japanese subtitle mirror
analysis:
  use_reference_scripts: false
```

The two API keys are secrets: the settings page never shows their values.

## Published cast from several catalogues

| Source | Key | What it adds | Limits |
|---|---|---|---|
| AniList | none | roles, gender, age, descriptions, voices in every language AniList tracks | per-IP rate limit |
| Anime News Network | none | casts for each dub (`lang="EN"`, `"ES"`, ...), staff such as ADR directors, episode titles | 1 request/s; batch reads of up to 50 entries |
| MyAnimeList via Jikan | none | voices per language, staff | about 60 requests/min; the public instance is sometimes unreachable |
| Bangumi | none | native-script names, Chinese coverage | actors' language is not stated |
| Kitsu | none | voices by locale, main and supporting roles | sparser dub credits; 1 request/s |

```
doblarr cast search SERIES [--source anilist|ann|jikan|bangumi|all]
doblarr cast suggest SERIES --source ann   # entries matching the linked title, with why
doblarr cast link SERIES URL [--why "same title, same year"]
doblarr cast show SERIES --merged          # every source side by side
```

Each catalogue's cast is stored as a separate `published_cast` record
(`<series>#ann`, `<series>#ann#s2`). AniList records keep the plain ids they had
before other catalogues were added. The merged view has one row per character,
matching names in any order and with romanization folded. It keeps every voice
by language along with the sources that credit it. Where catalogues disagree on
gender or age, the row says so and no value is chosen. An import adds every
source's voices to a character's published facts.

## Questions (prompture.research)

```
doblarr research SERIES "How does the Latin American dub say the guild's name?"
```

The question goes to Prompture's `ResearchAgent`, with the title appended when
the question doesn't name it. The agent searches without a key, reads a few
pages, and writes an answer whose `[n]` citations refer only to pages it
opened. One model plans the searches and writes the answer, within the
`research.depth` preset and `research.max_cost_usd`. In the app, a question
runs as a job (`studio_research`), and each run is kept as a `research_run`
record, so you can read it again later without paying for it again.

From the answer:

- the cited text becomes an external narrative claim with its source URLs
  (Knowledge → Narrative);
- names and terms become `proposed` show-scoped (or film-scoped) knowledge
  entries, and are also written to `work/research/<run>/candidates.jsonl` for
  `scripts/import_knowledge_candidates.py`;
- dub voices that no linked catalogue lists become **cast leads**. An accepted
  lead joins the series' `research` cast record and appears in the merged view.

## Reference scripts

```
doblarr scripts SERIES --sources fandom,screenplays,kitsunekko,opensubtitles,dubbing
```

| Source | Finds | Notes |
|---|---|---|
| Fandom wikis | episode transcripts with speakers | wiki guessed from the title, or named with `--wiki`; reads the `Transcript` namespace and `.../Transcript` pages through the MediaWiki API |
| IMSDb, Script Slug | film screenplays with character cues | fetched through Prompture's `web_fetch` |
| Springfield! Springfield! | film and episode transcripts | dialogue only, no speakers |
| kitsunekko mirror | Japanese subtitles | read from your local clone; nothing per title goes online |
| OpenSubtitles | subtitles in other languages | needs a free key; about 20 downloads a day |
| Dubbing Database | dub casts in free text | read by the research model into cast leads |

Each found script is a `title_script` record with its source and URL. A page
whose title names no episode is matched using the episode titles a linked
catalogue lists (ANN), or you can set the episode on the Research tab. Scripts
are kept for local analysis and never redistributed. Ripping subtitles from
streaming services is out of scope.

With `analysis.use_reference_scripts` on, knowledge extraction aligns the
episode's reference script to its subtitle cues by their words, in order, and
gives the model the matched lines as `reference_transcript`. Lines that don't
match are left out. The draft records that a reference was used, so a draft
built with a reference and one built without it never share cached windows.

## Ids and other names

```
doblarr titles SERIES --refresh
```

Starting from any id Doblarr already holds (the TVDB or TMDB id, or a linked
catalogue entry), Wikidata returns the title's ids in ANN, MyAnimeList,
AniList, Bangumi, Kitsu, IMDb, TVDB and TMDB. If the ids you supply point to
different titles, none of the results are kept. With a key, TMDB adds the
title's names by language and region. Probes use these names when they look
for wikis and subtitle folders.

## Not covered yet

Behind the Voice Actors (scrape-only) and AniDB (registered client, strict
anti-leech rules) are possible future sources. Forever Dreaming,
SubsLikeScript and ourboard.org are excluded because they block automated
access. TVDB is excluded because it is paid.
