# Release process

Every application release **must** update the notes surface before the version tag is cut.

## Files to update (checklist)

| #   | File                 | Purpose                                                              |
| --- | -------------------- | -------------------------------------------------------------------- |
| 1   | `docs/releases.json` | **Source of truth** for the in-app What's New page                   |
| 2   | `docs/BUGFIXES.md`   | Bug fixes only (support / QA)                                        |
| 3   | `CHANGELOG.md`       | GitHub-facing full changelog (Added / Fixed / Security)              |
| 4   | `config.py`          | Set `APP_VERSION = "X.Y.Z"` to match the release                     |
| 5   | `README.md`          | Refresh the **Features** bullets if user-facing capabilities changed |

## Steps

1. **Collect changes** since the last tag (`git log vA.B.C..HEAD --oneline`).
2. **Split** into features vs fixes (and security if any).
3. **Edit `docs/releases.json`** — prepend a new object with `version`, `date`, `title`, `features`, `fixes`.
4. **Edit `docs/BUGFIXES.md`** — prepend a `## X.Y.Z` section with fix bullets only.
5. **Edit `CHANGELOG.md`** — prepend `## [X.Y.Z] — YYYY-MM-DD` with `### Added` / `### Fixed` / `### Security`.
6. **Bump `APP_VERSION`** in `config.py`.
7. **Update README Features** if the user-visible capability list changed.
8. Commit: `docs: release X.Y.Z notes (What's New, CHANGELOG, BUGFIXES)`.
9. Tag exactly `vX.Y.Z` (no dot after the `v`; `v.2.5.1` was a typo): `git tag -a vX.Y.Z -m "vX.Y.Z"` and push the tag (moves `stable`/`latest` images per CI policy).

## What's New page

`views/whats_new.py` loads `docs/releases.json` at runtime. **Do not** hard-code release bullets in the view.

## Do not

- Ship a version bump without updating the files above.
- Put feature marketing copy into `BUGFIXES.md`.
- Leave `APP_VERSION` behind the git tag. `tests/test_audit_fixes.py::test_release_notes_match_app_version` fails CI if `config.py`, `docs/releases.json` and `CHANGELOG.md` disagree.
- Cut a tag while `pytest` or the pyflakes step is red.
