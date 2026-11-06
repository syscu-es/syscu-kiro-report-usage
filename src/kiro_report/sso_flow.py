"""Sign in to any AWS account through IAM Identity Center, no pre-configured profile needed.

Uses the OAuth device-authorization flow (the same one ``aws sso login`` uses): the user
approves in the browser, then we list the accounts/roles the identity can reach and obtain
short-lived role credentials. Tokens and credentials live in memory only.
"""
from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .aws import AuthError

CLIENT_NAME = "kiro-report"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
DEFAULT_TIMEOUT_S = 300
_SLOW_DOWN_STEP_S = 5


class SsoError(AuthError):
    """IAM Identity Center sign-in failed."""


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    email: str = ""


@dataclass(frozen=True)
class Role:
    account_id: str
    name: str


def _code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def device_login(
    start_url: str,
    region: str,
    *,
    client_factory: Callable[..., Any] = boto3.client,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    open_url: Callable[[str], Any] = webbrowser.open,
    say: Callable[[str], None] = print,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> str:
    """Run the device flow and return an SSO access token."""
    try:
        oidc = client_factory("sso-oidc", region_name=region)
        registration = oidc.register_client(clientName=CLIENT_NAME, clientType="public")
        auth = oidc.start_device_authorization(
            clientId=registration["clientId"], clientSecret=registration["clientSecret"], startUrl=start_url
        )
    except (BotoCoreError, ClientError) as exc:
        raise SsoError(f"could not start IAM Identity Center sign-in: {exc}") from exc

    url = auth.get("verificationUriComplete") or auth["verificationUri"]
    say(f"\nApprove the sign-in in your browser: {url}\n  (code: {auth['userCode']})")
    try:
        open_url(url)
    except Exception:  # noqa: BLE001 - a missing browser must not abort; the URL is printed above
        pass

    interval = float(auth.get("interval", 5))
    deadline = clock() + min(timeout, float(auth.get("expiresIn", timeout)))
    while clock() < deadline:
        try:
            token = oidc.create_token(
                clientId=registration["clientId"], clientSecret=registration["clientSecret"],
                grantType=DEVICE_GRANT, deviceCode=auth["deviceCode"],
            )
            return token["accessToken"]
        except ClientError as exc:
            code = _code(exc)
            if code == "AuthorizationPendingException":
                sleep(interval)
            elif code == "SlowDownException":
                interval += _SLOW_DOWN_STEP_S
                sleep(interval)
            else:
                raise SsoError(f"sign-in was not completed ({code or exc})") from exc
    raise SsoError("timed out waiting for the browser approval")


def _sso(region: str, client_factory: Callable[..., Any]) -> Any:
    return client_factory("sso", region_name=region)


def list_accounts(
    token: str, region: str, *, client_factory: Callable[..., Any] = boto3.client
) -> list[Account]:
    try:
        pages = _sso(region, client_factory).get_paginator("list_accounts").paginate(accessToken=token)
        accounts = [
            Account(a["accountId"], a.get("accountName", ""), a.get("emailAddress", ""))
            for page in pages for a in page.get("accountList", [])
        ]
    except (BotoCoreError, ClientError) as exc:
        raise SsoError(f"could not list accounts: {exc}") from exc
    return sorted(accounts, key=lambda a: (a.name.lower(), a.id))


def list_roles(
    token: str, region: str, account_id: str, *, client_factory: Callable[..., Any] = boto3.client
) -> list[Role]:
    try:
        pages = _sso(region, client_factory).get_paginator("list_account_roles").paginate(
            accessToken=token, accountId=account_id)
        roles = [Role(account_id, r["roleName"]) for page in pages for r in page.get("roleList", [])]
    except (BotoCoreError, ClientError) as exc:
        raise SsoError(f"could not list roles for {account_id}: {exc}") from exc
    return sorted(roles, key=lambda r: r.name)


def role_session(
    token: str,
    region: str,
    role: Role,
    client_region: str | None = None,
    *,
    client_factory: Callable[..., Any] = boto3.client,
    session_factory: Callable[..., Any] = boto3.Session,
) -> Any:
    """A boto3 session using the role's temporary credentials."""
    try:
        creds = _sso(region, client_factory).get_role_credentials(
            roleName=role.name, accountId=role.account_id, accessToken=token)["roleCredentials"]
    except (BotoCoreError, ClientError) as exc:
        raise SsoError(f"could not get credentials for {role.name}@{role.account_id}: {exc}") from exc
    return session_factory(
        aws_access_key_id=creds["accessKeyId"],
        aws_secret_access_key=creds["secretAccessKey"],
        aws_session_token=creds["sessionToken"],
        region_name=client_region or region,
    )
