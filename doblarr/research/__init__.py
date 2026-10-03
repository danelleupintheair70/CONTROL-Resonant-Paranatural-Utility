"""Title research: public sources about a title, kept for review (docs/title-research.md).

- `agent` asks the web a question through Prompture's research agent and
  lands what it finds as proposals: an external narrative claim, show-scoped
  knowledge entries, cast leads.
- `fandom`, `screenplays`, `jpsubs` and `opensubs` look for reference
  scripts and subtitles, kept as `title_script` records apart from evidence.
- `titles` gathers a title's other names and catalogue ids.

Nothing here runs on its own. Only a title or a question leaves the machine,
when a person asks, and nothing found is applied without a person's review.
"""
