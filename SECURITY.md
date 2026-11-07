# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting:
**Security → Report a vulnerability** on <https://github.com/syscu-es/syscu-kiro-report-usage>.

We aim to acknowledge reports within 5 working days and to publish a fix and advisory once a patch is available.

## Supported versions

Only the latest released version on [PyPI](https://pypi.org/project/syscu-kiro-report-usage/) receives fixes.

## What the tool does with your data (scope)

- It is **read-only** against AWS (see [docs/PERMISSIONS.md](docs/PERMISSIONS.md)) and never writes to your accounts.
- AWS credentials, IAM Identity Center tokens and role credentials are kept **in memory only** and never written to disk or sent anywhere except the AWS APIs.
- Downloaded CUR parquet files and activity CSVs are cached under `~/.cache/kiro-report` (override with `--cache-dir`). They can contain user e-mails and usage data: protect that directory like any billing export.
- Generated reports contain user e-mails and usage. Use `--anonymize` before sharing them; never commit them (they are git-ignored).

## Hardening notes for maintainers

- Releases are published with PyPI Trusted Publishing (OIDC), with no stored tokens.
- CI runs on a self-hosted runner: pull requests from forks do not run there automatically (see `.github/workflows/ci.yml`).
