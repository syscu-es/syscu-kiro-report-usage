# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-07

Documentation and packaging metadata only; no behaviour changes.

### Added
- Community files: `SECURITY.md`, `CONTRIBUTING.md`, issue and pull request templates.
- Dependabot for GitHub Actions and Python dependencies.
- README badges; package classifiers.

### Changed
- CI no longer runs pull requests from forks on the self-hosted runner.
- The release workflow publishes with `uv publish` (Trusted Publishing); the Docker-based PyPI action cannot see the workspace on the containerised self-hosted runners.
- Repository history now uses the GitHub noreply address and generic fixture names.

## [0.1.0] - 2026-11-07

First public release.

### Added
- `kiro-report` CLI that generates a single self-contained HTML report of Kiro usage and cost per IAM Identity Center user.
- Interactive account selection: local AWS profiles, the default credential chain, or sign-in to **any account through IAM Identity Center** (device flow, no profile needed).
- Period selection (`--month`, `--since`/`--until`, `--last`) or interactive prompt.
- Data sources: AWS Cost and Usage Report (parquet) and the Kiro user activity report (S3 CSV); either may be missing.
- CUR discovery by Data Export, with a bucket-scan fallback for roles without `bcm-data-exports:ListExports` (e.g. `ReadOnlyAccess`).
- Report: date-range and daily/weekly/monthly filters, credits by client type and plan, active users, models, overage, per-person detail, subscription cost, tier right-sizing recommendations, English/Spanish, light/dark theme.
- `--demo` (synthetic data), `--anonymize`, branding options, `--json` export.
- Trusted Publishing release workflow.
