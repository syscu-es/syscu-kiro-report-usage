"""AWS profile selection, session creation and (SSO) credential handling."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Callable

import boto3
import botocore.session
from botocore.exceptions import BotoCoreError, ClientError

_SSO_KEYS = ("sso_start_url", "sso_session")


class AuthError(RuntimeError):
    """Credentials are missing, expired or could not be refreshed."""


@dataclass(frozen=True)
class ProfileInfo:
    name: str
    kind: str  # 'sso' | 'role' | 'keys' | 'other'
    account: str | None
    region: str | None

    def label(self) -> str:
        extra = [self.kind] + ([f"account {self.account}"] if self.account else [])
        return f"{self.name}  ({', '.join(extra)})"


def _scoped_config(profile: str | None) -> dict[str, Any]:
    try:
        return botocore.session.Session(profile=profile).get_scoped_config()
    except Exception:  # unknown profile or unreadable config: treat as empty
        return {}


def profile_kind(config: dict[str, Any]) -> str:
    if any(k in config for k in _SSO_KEYS):
        return "sso"
    if "role_arn" in config:
        return "role"
    if "aws_access_key_id" in config:
        return "keys"
    return "other"


def list_profiles() -> list[ProfileInfo]:
    """Profiles from ~/.aws/config and ~/.aws/credentials (secrets are never read out)."""
    out = []
    for name in sorted(botocore.session.Session().available_profiles):
        cfg = _scoped_config(name)
        out.append(ProfileInfo(name, profile_kind(cfg), cfg.get("sso_account_id"), cfg.get("region")))
    return out


def is_sso_profile(profile: str | None) -> bool:
    return profile_kind(_scoped_config(profile)) == "sso" if profile else False


def open_session(profile: str | None, region: str | None = None) -> boto3.Session:
    return boto3.Session(profile_name=profile, region_name=region)


def caller_account(session: Any) -> str:
    return session.client("sts").get_caller_identity()["Account"]


def ensure_credentials(
    profile: str | None,
    region: str | None = None,
    *,
    auto_login: bool = False,
    confirm: Callable[[str], bool] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    opener: Callable[[str | None, str | None], Any] = open_session,
) -> tuple[Any, str]:
    """Return ``(session, account_id)``, running ``aws sso login`` when an SSO profile
    has no valid token (automatically with ``auto_login`` or after ``confirm``)."""
    session = opener(profile, region)
    try:
        return session, caller_account(session)
    except (BotoCoreError, ClientError) as first_error:
        if not is_sso_profile(profile):
            raise AuthError(
                f"Could not authenticate ({first_error}). Check the profile/credentials; "
                "for SSO profiles run `aws sso login --profile <name>`."
            ) from first_error
        wanted = auto_login or (confirm is not None and confirm(
            f"SSO session for '{profile}' is missing or expired. Run `aws sso login` now?"))
        if not wanted:
            raise AuthError(f"SSO login required: run `aws sso login --profile {profile}`.") from first_error
        try:
            code = runner(["aws", "sso", "login", "--profile", profile]).returncode
        except FileNotFoundError as exc:
            raise AuthError("The AWS CLI (`aws`) is required for SSO login but was not found.") from exc
        if code != 0:
            raise AuthError(f"`aws sso login --profile {profile}` failed (exit code {code}).") from first_error
        session = opener(profile, region)
        try:
            return session, caller_account(session)
        except (BotoCoreError, ClientError) as second_error:
            raise AuthError(f"Still unauthenticated after SSO login: {second_error}") from second_error
