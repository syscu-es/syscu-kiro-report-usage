# Contributing

Thanks for helping! Bug reports, ideas and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/syscu-es/syscu-kiro-report-usage.git
cd syscu-kiro-report-usage
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # Python 3.10+
```

Preview the report without any AWS access:

```bash
kiro-report --demo --open
```

## Before you open a pull request

```bash
ruff check .                      # lint
pytest --cov=kiro_report          # tests (CI requires >= 80% coverage)
```

- Add or update **tests** for behaviour changes. Tests must not need AWS: use the fakes in `tests/`.
- Keep functions small and files focused; prefer returning new objects over mutating inputs.
- Use [conventional commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`.
- Update `README.md` / `docs/` and add a line to `CHANGELOG.md` under *Unreleased*.

## Never commit real data

Generated reports (`kiro-report-*.html`, `*.json`), CUR files and activity CSVs contain user e-mails and usage. They are git-ignored; please keep it that way. Use `--demo` or `--anonymize` for screenshots and examples, and fake data (`example.com`) in tests.

## CI and pull requests from forks

CI runs on a self-hosted runner, so it **does not run automatically for pull requests from forks**. A maintainer will review the diff and run the checks (or check out the branch) before merging. Running `ruff` and `pytest` locally first speeds this up.

## Reporting security issues

See [SECURITY.md](SECURITY.md); do not use public issues.

## Releasing (maintainers)

Bump `version` in `pyproject.toml`, update `CHANGELOG.md`, merge, then push a tag `vX.Y.Z`. The `release` workflow builds, validates and publishes to PyPI through Trusted Publishing, with a manual approval on the `pypi` environment.
