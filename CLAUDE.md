# Doblarr

## Before every commit

Run the same checks CI runs, from the repo root:

```powershell
.\dev.ps1 validate once
```

It runs ruff, `mypy doblarr/`, eslint, the UI unit tests, the UI build and
pytest, and exits 1 if any fails. Commit only when it ends with `all good`.
Checking only the files you touched is not enough: CI runs `ruff check .` and
`mypy doblarr/` over the whole package, and mypy catches what ruff does not.

`.\dev.ps1 check` runs everything CI runs except the docker build, including
the Playwright browser tests that `validate once` skips. Run it before pushing
anything meant for a pull request: the gates to `master` run the browser
tests on Linux, whose fallback font is wider than Windows', so a page that
fits 390 px here can overflow there. Put every wide table in a
`overflow-x: auto` wrapper.

## Conventions

- Tests, fixtures, comments and commit messages use invented names (the show
  "Harbor Lights", characters Kaito, Mina, Ren, Sora, Tomoe). Never real
  titles, characters, show vocabulary, library paths or catalogue ids. Real
  names may appear only in git-ignored places (`work/`, `docs/plans/`).
- The repo does not run `ruff format`; ruff check with safe fixes only.
