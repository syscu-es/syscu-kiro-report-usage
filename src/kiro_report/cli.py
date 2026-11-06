"""Command line interface: ``kiro-report``.

Interactive by default on a terminal (asks for the AWS profile and the period); every
question has a flag so it also runs unattended in CI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import locale
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from botocore.exceptions import BotoCoreError, ClientError

from . import __version__, activity, aws, cur, identity, sso_flow
from .demo import make_demo
from .ids import normalize_user_id
from .model import build_report
from .periods import PeriodError, month_range, preset_choices, resolve_period
from .render import load_branding, render

EXIT_OK, EXIT_AUTH, EXIT_USAGE, EXIT_NO_DATA = 0, 1, 2, 3
SSO_SIGNIN = "<sso-signin>"  # sentinel returned by choose_profile for "sign in with Identity Center"
DEFAULT_SSO_REGION = "us-east-1"
DEFAULT_CACHE = Path(os.environ.get("KIRO_REPORT_CACHE", Path.home() / ".cache" / "kiro-report"))


def log(message: str) -> None:
    print(message, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kiro-report",
        description="Generate a self-contained HTML report of Kiro usage and cost per "
                    "IAM Identity Center user (AWS CUR + Kiro user activity report).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    acct = p.add_argument_group("account")
    acct.add_argument("--profile", help="AWS profile (omit to be asked, or to use the default chain)")
    acct.add_argument("--region", help="AWS region for client calls (default: profile/env)")
    acct.add_argument("--sso-login", action="store_true",
                      help="run `aws sso login` automatically when the SSO session is expired")
    acct.add_argument("--sso-start-url", help="sign in to ANY account through IAM Identity Center "
                      "(https://<name>.awsapps.com/start); no AWS profile needed")
    acct.add_argument("--sso-region", help=f"Identity Center region (default: {DEFAULT_SSO_REGION})")
    acct.add_argument("--sso-account", help="account id or name to use after SSO sign-in")
    acct.add_argument("--sso-role", help="permission-set/role name to use after SSO sign-in")
    per = p.add_argument_group("period (default: last 3 months, or asked interactively)")
    per.add_argument("--month", help="a single month, YYYY-MM")
    per.add_argument("--since", help="first month, YYYY-MM")
    per.add_argument("--until", help="last month, YYYY-MM (default: current month)")
    per.add_argument("--last", type=int, help="the last N months including the current one")
    src = p.add_argument_group("data sources (auto-discovered when omitted)")
    src.add_argument("--no-cur", action="store_true", help="skip the Cost and Usage Report")
    src.add_argument("--no-activity", action="store_true", help="skip the Kiro activity report")
    src.add_argument("--cur-export", help="name of the CUR Data Export")
    src.add_argument("--cur-bucket", help="CUR bucket (with --cur-prefix)")
    src.add_argument("--cur-prefix", help="CUR prefix up to and including .../data")
    src.add_argument("--activity-bucket", help="bucket receiving the Kiro activity reports")
    src.add_argument("--activity-prefix", help="key prefix before AWSLogs/ (default: auto-detected)")
    src.add_argument("--identity-store-id", help="d-xxxxxxxxxx (auto-discovered when omitted)")
    src.add_argument("--identity-region", default="us-east-1", help="IAM Identity Center region")
    out = p.add_argument_group("output")
    out.add_argument("--out", help="HTML file to write (default: kiro-report-<account>-<period>.html)")
    out.add_argument("--json", metavar="FILE", help="also write the aggregated data as JSON")
    out.add_argument("--lang", choices=["en", "es"], help="report language (default: from locale)")
    out.add_argument("--anonymize", action="store_true", help="replace user names with user-NN")
    out.add_argument("--brand", help="brand name shown in the header (default: SysCu)")
    out.add_argument("--logo", type=Path, help="logo file (svg/png/jpg) replacing the bundled one")
    out.add_argument("--no-logo", action="store_true", help="omit the logo")
    out.add_argument("--no-embed-font", action="store_true", help="do not embed the Figtree font")
    out.add_argument("--open", action="store_true", help="open the report when done")
    run = p.add_argument_group("behaviour")
    run.add_argument("--demo", action="store_true", help="render synthetic data, no AWS access needed")
    run.add_argument("-y", "--yes", action="store_true", help="never prompt; use defaults")
    run.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE, help="download cache")
    return p


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def prompt_choice(
    input_fn: Callable[[str], str],
    title: str,
    options: list[str],
    default: int = 0,
    *,
    filterable: bool = False,
) -> int:
    """Numbered single-choice prompt; Enter selects ``default``.

    With ``filterable`` (long lists such as AWS accounts) typing text narrows the list by
    case-insensitive substring; the returned index always refers to ``options``.
    """
    log(f"\n{title}")
    for i, label in enumerate(options, 1):
        log(f"  {i}) {label}{'  [default]' if i - 1 == default else ''}")
    hint = " or type text to filter" if filterable else ""
    while True:
        answer = input_fn(f"Choose 1-{len(options)}{hint} [{default + 1}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        if filterable and not answer.isdigit():
            hits = [i for i, label in enumerate(options) if answer.lower() in label.lower()]
            if len(hits) == 1:
                return hits[0]
            if hits:
                sub = prompt_choice(input_fn, f"{title} (filtered by '{answer}')",
                                    [options[i] for i in hits], 0, filterable=True)
                return hits[sub]
            log("  no match")
            continue
        log("  invalid choice")


def choose_profile(input_fn: Callable[[str], str]) -> str | None:
    """Pick a local AWS profile, ``SSO_SIGNIN`` (any account via Identity Center) or ``None``
    (default credential chain)."""
    profiles = aws.list_profiles()
    labels = (
        [p.label() for p in profiles]
        + ["Sign in with AWS IAM Identity Center (SSO) - any account you can access"]
        + ["(default credential chain: env vars / instance role)"]
    )
    preset = os.environ.get("AWS_PROFILE")
    default = next((i for i, p in enumerate(profiles) if p.name == preset),
                   0 if profiles else len(profiles))
    picked = prompt_choice(input_fn, "AWS account / profile", labels, default, filterable=True)
    if picked < len(profiles):
        return profiles[picked].name
    return SSO_SIGNIN if picked == len(profiles) else None


def _select(items: list[Any], wanted: str | None, ask: bool, input_fn: Callable[[str], str],
            title: str, label: Callable[[Any], str], key: Callable[[Any], str], flag: str) -> Any:
    """Choose one of ``items`` by flag value, automatically if unique, or interactively."""
    if not items:
        raise aws.AuthError(f"no {title.lower()} available for this identity")
    if wanted:
        hit = next((i for i in items if key(i) == wanted or wanted.lower() in label(i).lower()), None)
        if hit is None:
            raise aws.AuthError(f"{flag} {wanted!r} not found; available: "
                                + ", ".join(label(i) for i in items))
        return hit
    if len(items) == 1:
        return items[0]
    if not ask:
        raise aws.AuthError(f"several options for {title.lower()}; pass {flag}. Available: "
                            + ", ".join(label(i) for i in items))
    return items[prompt_choice(input_fn, title, [label(i) for i in items], filterable=True)]


def sso_session_from_prompts(
    args: argparse.Namespace, ask: bool, input_fn: Callable[[str], str]
) -> tuple[Any, str, str]:
    """Sign in to any account through IAM Identity Center (device flow) and pick account/role.

    Returns ``(session, account_id, label)``. Tokens and credentials stay in memory only.
    """
    start_url = args.sso_start_url or os.environ.get("KIRO_REPORT_SSO_START_URL", "")
    if ask and not args.sso_start_url:
        shown = start_url or "https://<name>.awsapps.com/start"
        start_url = input_fn(f"IAM Identity Center start URL [{shown}]: ").strip() or start_url
    if not start_url:
        raise aws.AuthError("an IAM Identity Center start URL is required (--sso-start-url)")
    region = args.sso_region or DEFAULT_SSO_REGION
    if ask and not args.sso_region:
        region = input_fn(f"Identity Center region [{DEFAULT_SSO_REGION}]: ").strip() or DEFAULT_SSO_REGION

    token = sso_flow.device_login(start_url, region, say=log)
    account = _select(sso_flow.list_accounts(token, region), args.sso_account, ask, input_fn,
                      "AWS account", lambda a: f"{a.id}  {a.name}", lambda a: a.id, "--sso-account")
    role = _select(sso_flow.list_roles(token, region, account.id), args.sso_role, ask, input_fn,
                   "Role", lambda r: r.name, lambda r: r.name, "--sso-role")
    session = sso_flow.role_session(token, region, role, args.region)
    return session, account.id, f"sso:{account.name}/{role.name}"


def choose_period(input_fn: Callable[[str], str], today: dt.date) -> tuple[str, str]:
    presets = preset_choices(today)
    labels = [label for label, _, _ in presets] + ["Custom (YYYY-MM or YYYY-MM:YYYY-MM)"]
    picked = prompt_choice(input_fn, "Period", labels, default=2)
    if picked < len(presets):
        return presets[picked][1], presets[picked][2]
    while True:
        text = input_fn("Period (e.g. 2026-10 or 2026-08:2026-10): ").strip()
        start, _, end = text.partition(":")
        try:
            return resolve_period(since=start, until=end or start, today=today)
        except PeriodError as exc:
            log(f"  {exc}")


def detect_lang() -> str:
    code = (os.environ.get("LC_ALL") or os.environ.get("LANG") or locale.getlocale()[0] or "").lower()
    return "es" if code.startswith("es") else "en"


# --------------------------------------------------------------------------- #
# Data collection
# --------------------------------------------------------------------------- #
def collect_cur(args: argparse.Namespace, session: Any, months: list[str]) -> tuple[cur.CurData | None, str | None]:
    if args.no_cur:
        return None, None
    try:
        if args.cur_bucket:
            if args.cur_prefix is None:
                raise ValueError("--cur-bucket requires --cur-prefix")
            source: cur.CurSource | None = cur.CurSource(
                args.cur_bucket, args.cur_prefix.strip("/"), args.cur_bucket)
        else:
            source = cur.discover(session, args.cur_export)
        if source is None:
            log("  CUR: no parquet Data Export with line_item_resource_id found (cost will be estimated)")
            return None, None
        log(f"  CUR: s3://{source.bucket}/{source.base}")
        s3 = session.client("s3")
        rows: list[tuple[str, dict[str, Any]]] = []
        for month in months:
            files = cur.fetch_month(s3, source, month, args.cache_dir, force=month >= months[-1])
            month_rows = list(cur.read_kiro_rows(files))
            log(f"  CUR {month}: {len(files)} file(s), {len(month_rows)} Kiro rows")
            rows.extend((month, r) for r in month_rows)
        return cur.aggregate(rows), source.export
    except (BotoCoreError, ClientError, ValueError) as exc:
        log(f"  CUR unavailable ({exc}); cost will be estimated at list price")
        return None, None


def collect_activity(
    args: argparse.Namespace, session: Any, account: str, months: list[str], today: dt.date
) -> tuple[list[activity.ActivityRow] | None, str | None]:
    if args.no_activity:
        return None, None
    try:
        s3 = session.client("s3")
        found = activity.discover(s3, bucket=args.activity_bucket, prefix=args.activity_prefix,
                                  account=account if args.activity_prefix is not None else None)
        if found.location is None:
            where = ", ".join(found.candidates) or "no bucket with 'kiro' in its name"
            log(f"  activity: no report files found ({where}). Enable the user activity report in "
                "the Kiro console (Settings) or pass --activity-bucket.")
            return None, None
        rows = activity.load_activity(s3, found.location, months, cache=args.cache_dir, today=today,
                                      progress=log)
        log(f"  activity: {len(rows)} rows from s3://{found.location.bucket}/{found.location.base}")
        return (rows or None), found.location.bucket
    except (BotoCoreError, ClientError) as exc:
        log(f"  activity reports unavailable ({exc})")
        return None, None


def collect_names(
    args: argparse.Namespace, session: Any, cur_data: cur.CurData | None,
    rows: list[activity.ActivityRow] | None,
) -> dict[str, str]:
    """Identity Center names, only for users whose e-mail the activity report did not give."""
    known = {normalize_user_id(r.user_id) for r in (rows or []) if r.email}
    missing = sorted(set(cur_data.users if cur_data else {}) - known)
    if not missing:
        return {}
    try:
        store = args.identity_store_id or identity.discover_identity_store(session, args.identity_region)
        return identity.resolve_names(session, store, args.identity_region, missing, log) if store else {}
    except (BotoCoreError, ClientError) as exc:
        log(f"  Identity Center lookup skipped ({exc}); users will show a short id")
        return {}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    interactive: bool | None = None,
    today: dt.date | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    today = today or dt.date.today()
    ask = (sys.stdin.isatty() and not args.yes) if interactive is None else interactive
    ask = ask and not args.yes
    lang = args.lang or detect_lang()

    data: dict[str, Any] | None
    try:
        if args.demo:
            data, label = make_demo(today), "demo"
        else:
            data, label = run_pipeline(args, ask, input_fn, today)
    except PeriodError as exc:
        log(f"error: {exc}")
        return EXIT_USAGE
    except aws.AuthError as exc:
        log(f"error: {exc}")
        return EXIT_AUTH
    if data is None:
        log("error: no Kiro data found in the selected period/sources.")
        return EXIT_NO_DATA

    try:
        branding = load_branding(args.brand, args.logo, no_logo=args.no_logo,
                                 embed_font=not args.no_embed_font)
    except (ValueError, OSError) as exc:
        log(f"error: {exc}")
        return EXIT_USAGE
    months = data["meta"]["months"]
    out = Path(args.out or f"kiro-report-{label}-{months[0]}_{months[-1]}.html")
    out.write_text(render(data, branding, lang), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"\n{len(data['people'])} users -> {out.resolve()}")
    if args.open:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(out)], check=False)
    return EXIT_OK


def run_pipeline(
    args: argparse.Namespace, ask: bool, input_fn: Callable[[str], str], today: dt.date
) -> tuple[dict[str, Any] | None, str]:
    profile = args.profile or (SSO_SIGNIN if args.sso_start_url else None)
    if profile is None and ask:
        profile = choose_profile(input_fn)
    has_period = any([args.month, args.since, args.until, args.last])
    if ask and not has_period:
        since, until = choose_period(input_fn, today)
    else:
        since, until = resolve_period(month=args.month, since=args.since, until=args.until,
                                      last=args.last, today=today)
    months = month_range(since, until)

    confirm = (lambda q: input_fn(f"{q} [Y/n]: ").strip().lower() in {"", "y", "yes", "s", "si"}) if ask else None
    if profile == SSO_SIGNIN:
        session, account, label = sso_session_from_prompts(args, ask, input_fn)
    else:
        session, account = aws.ensure_credentials(profile, args.region, auto_login=args.sso_login,
                                                  confirm=confirm)
        label = f"profile {profile or '(default chain)'}"
    log(f"\naccount {account} | {label} | {months[0]}..{months[-1]}")

    cur_data, cur_source = collect_cur(args, session, months)
    rows, activity_source = collect_activity(args, session, account, months, today)
    if cur_data is None and rows is None:
        return None, account
    names = collect_names(args, session, cur_data, rows)
    meta = {"account": account, "source_cur": cur_source, "source_activity": activity_source}
    data = build_report(meta=meta, months=months, cur=cur_data, activity=rows, names=names,
                        today=today, anonymize=args.anonymize)
    return (data if data["people"] else None), account


if __name__ == "__main__":
    sys.exit(main())
