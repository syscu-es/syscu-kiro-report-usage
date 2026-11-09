# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Engagement section in the report: user segments (power / active / light / idle) based on the share of the plan allowance used (message/conversation thresholds as fallback when the plan is unknown), an engagement funnel, top 10 users by messages, and a last-activity timeline with segment and recency filters.
- Per-user filter (usage, people and engagement views), metric definitions panel, and client-side CSV export of the people and engagement tables (spreadsheet formulas are neutralised).
- Optional Terraform module (`terraform/`): encrypted S3 bucket for the Kiro user activity report with the policy Kiro needs, optional CUR 2.0 Data Export, and a least-privilege read-only IAM policy/role for `kiro-report`.
- End-of-month projection per user (`forecast` module): projected credits and overage at the current pace, with findings for users on course to exceed their plan or to use over 80% of it.
- Credits by day of week (weekend share) in the usage section.
- `engagement` module and `people[].eng`, `people[].proj`, `meta.thresholds`, `meta.period_days`, `meta.proj_month` in the `--json` output.
- Credit to [`aws-samples/sample-kiro-user-analytics-dashboard`](https://github.com/aws-samples/sample-kiro-user-analytics-dashboard), which inspired these additions.

### Changed
- User, client, plan and account names are HTML-escaped everywhere the report renders them, and the embedded JSON now escapes `<`, `>`, `&` and U+2028/2029 (a crafted name such as `<!--<script>` can no longer break the page).
- The demo data now includes an idle user (no more phantom conversation on zero-message days).

### Fixed
- `kiro-report --version` reported `0.1.0` on 0.1.1: the version is now read from the installed package metadata instead of a second hard-coded copy.

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
