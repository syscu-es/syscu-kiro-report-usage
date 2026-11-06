import argparse

import pytest
from botocore.exceptions import ClientError

from kiro_report import aws, cli, sso_flow


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "CreateToken")


class FakeOidc:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def register_client(self, **_):
        return {"clientId": "cid", "clientSecret": "sec"}

    def start_device_authorization(self, **_):
        return {"verificationUriComplete": "https://device/?c=ABCD", "userCode": "ABCD",
                "deviceCode": "dev", "interval": 1, "expiresIn": 600}

    def create_token(self, **_):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"accessToken": outcome}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def login(outcomes, timeout=300):
    clock, said, opened = Clock(), [], []
    oidc = FakeOidc(outcomes)
    token = sso_flow.device_login(
        "https://x.awsapps.com/start", "us-east-1", client_factory=lambda *a, **k: oidc,
        sleep=clock.sleep, clock=clock, open_url=opened.append, say=said.append, timeout=timeout)
    return token, oidc, said, opened


@pytest.mark.unit
def test_device_login_polls_until_approved_and_opens_browser():
    token, oidc, said, opened = login([client_error("AuthorizationPendingException"),
                                       client_error("SlowDownException"), "TOKEN"])
    assert token == "TOKEN" and oidc.calls == 3
    assert opened == ["https://device/?c=ABCD"] and "ABCD" in said[0]


@pytest.mark.unit
def test_device_login_denied_and_timeout():
    with pytest.raises(sso_flow.SsoError, match="not completed"):
        login([client_error("AccessDeniedException")])
    with pytest.raises(sso_flow.SsoError, match="timed out"):
        login([client_error("AuthorizationPendingException")] * 50, timeout=3)


@pytest.mark.unit
def test_device_login_survives_missing_browser_and_wraps_start_errors():
    class NoBrowser(FakeOidc):
        pass

    oidc = NoBrowser(["T"])

    def boom(_url):
        raise RuntimeError("no browser")

    assert sso_flow.device_login("u", "r", client_factory=lambda *a, **k: oidc, open_url=boom,
                                 say=lambda _m: None, sleep=lambda _s: None) == "T"

    def failing(*_a, **_k):
        raise client_error("InvalidRequestException")

    with pytest.raises(sso_flow.SsoError, match="could not start"):
        sso_flow.device_login("u", "r", client_factory=failing, say=lambda _m: None)


class FakeSso:
    def __init__(self):
        self.last = {}

    def get_paginator(self, name):
        self.name = name
        return self

    def paginate(self, **kwargs):
        self.last = kwargs
        if self.name == "list_accounts":
            return [{"accountList": [{"accountId": "2", "accountName": "Zeta"},
                                     {"accountId": "1", "accountName": "alpha", "emailAddress": "a@x"}]}]
        return [{"roleList": [{"roleName": "Zed"}, {"roleName": "Admin"}]}]

    def get_role_credentials(self, **kwargs):
        self.last = kwargs
        return {"roleCredentials": {"accessKeyId": "AK", "secretAccessKey": "SK", "sessionToken": "ST"}}


@pytest.mark.unit
def test_list_accounts_roles_and_role_session():
    sso = FakeSso()
    factory = lambda *a, **k: sso  # noqa: E731
    accounts = sso_flow.list_accounts("tok", "us-east-1", client_factory=factory)
    assert [a.name for a in accounts] == ["alpha", "Zeta"] and accounts[0].email == "a@x"
    roles = sso_flow.list_roles("tok", "us-east-1", "1", client_factory=factory)
    assert [r.name for r in roles] == ["Admin", "Zed"] and sso.last["accountId"] == "1"
    seen = {}
    sso_flow.role_session("tok", "us-east-1", roles[0], "eu-west-1", client_factory=factory,
                          session_factory=lambda **kw: seen.update(kw) or "SESSION")
    assert seen == {"aws_access_key_id": "AK", "aws_secret_access_key": "SK",
                    "aws_session_token": "ST", "region_name": "eu-west-1"}


@pytest.mark.unit
def test_api_errors_are_wrapped():
    def failing(*_a, **_k):
        raise client_error("UnauthorizedException")

    with pytest.raises(sso_flow.SsoError):
        sso_flow.list_accounts("t", "r", client_factory=failing)
    with pytest.raises(sso_flow.SsoError):
        sso_flow.list_roles("t", "r", "1", client_factory=failing)
    with pytest.raises(sso_flow.SsoError):
        sso_flow.role_session("t", "r", sso_flow.Role("1", "x"), client_factory=failing)


# ------------------------------------------------------------------ cli glue
def args(**over):
    base = dict(sso_start_url="https://x.awsapps.com/start", sso_region=None, sso_account=None,
                sso_role=None, region=None)
    return argparse.Namespace(**{**base, **over})


@pytest.fixture
def fake_sso(monkeypatch):
    accounts = [sso_flow.Account("111", "Prod"), sso_flow.Account("222", "Dev")]
    roles = [sso_flow.Role("111", "Admin"), sso_flow.Role("111", "ReadOnly")]
    monkeypatch.setattr(sso_flow, "device_login", lambda *a, **k: "TOKEN")
    monkeypatch.setattr(sso_flow, "list_accounts", lambda *a, **k: accounts)
    monkeypatch.setattr(sso_flow, "list_roles", lambda *a, **k: roles)
    monkeypatch.setattr(sso_flow, "role_session", lambda token, region, role, cr=None, **k: ("S", role.name))
    return accounts, roles


@pytest.mark.unit
def test_cli_sso_non_interactive_uses_flags(fake_sso):
    session, account, label = cli.sso_session_from_prompts(
        args(sso_account="Dev", sso_role="ReadOnly"), False, lambda _p: "")
    assert (session, account, label) == (("S", "ReadOnly"), "222", "sso:Dev/ReadOnly")


@pytest.mark.unit
def test_cli_sso_interactive_prompts_for_url_region_account_and_role(fake_sso):
    answers = iter(["https://y.awsapps.com/start", "eu-west-1", "prod", "2"])
    session, account, label = cli.sso_session_from_prompts(args(sso_start_url=None), True,
                                                           lambda _p: next(answers))
    assert account == "111" and label == "sso:Prod/ReadOnly"


@pytest.mark.unit
def test_cli_sso_errors(fake_sso):
    with pytest.raises(aws.AuthError, match="start URL"):
        cli.sso_session_from_prompts(args(sso_start_url=None), False, lambda _p: "")
    with pytest.raises(aws.AuthError, match="not found"):
        cli.sso_session_from_prompts(args(sso_account="nope"), False, lambda _p: "")
    with pytest.raises(aws.AuthError, match="--sso-account"):
        cli.sso_session_from_prompts(args(), False, lambda _p: "")


@pytest.mark.unit
def test_prompt_choice_filters_long_lists():
    options = ["111  Prod", "222  Dev", "333  Prod-EU"]
    assert cli.prompt_choice(lambda _p: "dev", "t", options, filterable=True) == 1
    answers = iter(["zzz", "prod", "2"])
    assert cli.prompt_choice(lambda _p: next(answers), "t", options, filterable=True) == 2
