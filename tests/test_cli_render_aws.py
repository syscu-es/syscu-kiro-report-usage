import datetime as dt
import json
import subprocess

import pytest
from botocore.exceptions import NoCredentialsError

from kiro_report import aws, cli, demo, render

TODAY = dt.date(2026, 11, 6)


# ----------------------------------------------------------------- render
@pytest.mark.unit
def test_render_fills_every_placeholder_and_escapes_script_close(tmp_path):
    data = demo.make_demo(TODAY)
    data["people"][0]["user"] = "</script><b>x"
    html = render.render(data, render.default_branding(), "es")
    for token in ("__DATA__", "__LANG__", "__BRAND_NAME__", "__LOGO_LIGHT__", "__LOGO_DARK__", "__FONT_CSS__"):
        assert token not in html
    assert '<html lang="es">' in html and "data:image/svg+xml;base64," in html and "font/woff2" in html
    assert html.count("</script>") == 1  # only the template's own closing tag; the payload is escaped
    assert "<\\/script><b>x" in html


@pytest.mark.unit
def test_load_branding_overrides(tmp_path):
    logo = tmp_path / "mine.png"
    logo.write_bytes(b"\x89PNG")
    brand = render.load_branding("ACME", logo, embed_font=False)
    assert brand.name == "ACME" and brand.logo_light == ("image/png", b"\x89PNG") and brand.font is None
    assert render.load_branding(no_logo=True).logo_light is None
    with pytest.raises(ValueError):
        render.load_branding(logo=tmp_path / "x.gif")


@pytest.mark.unit
def test_render_without_logo_and_font_leaves_empty_sources():
    html = render.render(demo.make_demo(TODAY), render.load_branding(no_logo=True, embed_font=False))
    assert 'src=""' in html and "font/woff2" not in html


# -------------------------------------------------------------------- cli
@pytest.mark.unit
def test_cli_demo_writes_html_and_json(tmp_path):
    out, js = tmp_path / "r.html", tmp_path / "r.json"
    code = cli.main(["--demo", "--yes", "--lang", "en", "--out", str(out), "--json", str(js)], today=TODAY)
    assert code == cli.EXIT_OK and out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert json.loads(js.read_text(encoding="utf-8"))["meta"]["demo"] is True


@pytest.mark.unit
def test_cli_rejects_invalid_period_before_touching_aws():
    assert cli.main(["--yes", "--month", "2026-13"], today=TODAY) == cli.EXIT_USAGE


@pytest.mark.unit
def test_cli_rejects_unsupported_logo(tmp_path):
    bad = tmp_path / "logo.gif"
    bad.write_bytes(b"x")
    assert cli.main(["--demo", "--yes", "--logo", str(bad), "--out", str(tmp_path / "o.html")], today=TODAY) == cli.EXIT_USAGE


@pytest.mark.unit
def test_prompt_choice_default_invalid_and_valid():
    answers = iter(["", "9", "abc", "2"])
    assert cli.prompt_choice(lambda _p: next(answers), "t", ["a", "b"], default=1) == 1
    assert cli.prompt_choice(lambda _p: next(answers), "t", ["a", "b"], default=0) == 1


@pytest.mark.unit
def test_choose_period_preset_and_custom():
    assert cli.choose_period(lambda _p: "1", TODAY) == ("2026-10", "2026-10")
    answers = iter(["6", "bad", "2026-08:2026-10"])
    assert cli.choose_period(lambda _p: next(answers), TODAY) == ("2026-08", "2026-10")


@pytest.mark.unit
def test_choose_profile_lists_profiles_and_supports_default_chain(monkeypatch):
    profiles = [aws.ProfileInfo("dev", "sso", "111", None), aws.ProfileInfo("prod", "keys", None, None)]
    monkeypatch.setattr(aws, "list_profiles", lambda: profiles)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    assert cli.choose_profile(lambda _p: "2") == "prod"
    assert cli.choose_profile(lambda _p: "3") == cli.SSO_SIGNIN
    assert cli.choose_profile(lambda _p: "4") is None
    monkeypatch.setattr(aws, "list_profiles", list)
    assert cli.choose_profile(lambda _p: "") == cli.SSO_SIGNIN  # no local profiles: SSO sign-in is the default
    assert cli.choose_profile(lambda _p: "2") is None


@pytest.mark.unit
def test_detect_lang_from_environment(monkeypatch):
    monkeypatch.setenv("LC_ALL", "es_CL.UTF-8")
    assert cli.detect_lang() == "es"
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert cli.detect_lang() == "en"


# -------------------------------------------------------------------- aws
class _Sts:
    def __init__(self, ok):
        self.ok = ok

    def get_caller_identity(self):
        if not self.ok:
            raise NoCredentialsError()
        return {"Account": "123456789012"}


class _Session:
    def __init__(self, ok):
        self.ok = ok

    def client(self, name):
        return _Sts(self.ok)


class _Runner:
    def __init__(self, code=0, missing=False):
        self.calls, self.code, self.missing = [], code, missing

    def __call__(self, cmd):
        if self.missing:
            raise FileNotFoundError
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.code)


def _opener(first_ok, after_login=True):
    state = {"n": 0}

    def open_(profile, region):
        state["n"] += 1
        return _Session(first_ok if state["n"] == 1 else after_login)
    return open_


@pytest.mark.unit
def test_profile_kind_detection():
    assert aws.profile_kind({"sso_session": "s"}) == "sso"
    assert aws.profile_kind({"role_arn": "x"}) == "role"
    assert aws.profile_kind({"aws_access_key_id": "x"}) == "keys"
    assert aws.profile_kind({}) == "other"
    assert "account 1" in aws.ProfileInfo("p", "sso", "1", None).label()


@pytest.mark.unit
def test_ensure_credentials_valid_session_needs_no_login():
    runner = _Runner()
    _, account = aws.ensure_credentials("p", opener=_opener(True), runner=runner)
    assert account == "123456789012" and runner.calls == []


@pytest.mark.unit
def test_ensure_credentials_non_sso_failure_raises(monkeypatch):
    monkeypatch.setattr(aws, "is_sso_profile", lambda p: False)
    with pytest.raises(aws.AuthError):
        aws.ensure_credentials("p", opener=_opener(False))


@pytest.mark.unit
def test_ensure_credentials_sso_auto_login_then_success(monkeypatch):
    monkeypatch.setattr(aws, "is_sso_profile", lambda p: True)
    runner = _Runner()
    _, account = aws.ensure_credentials("p", auto_login=True, opener=_opener(False), runner=runner)
    assert account == "123456789012" and runner.calls == [["aws", "sso", "login", "--profile", "p"]]


@pytest.mark.unit
def test_ensure_credentials_sso_asks_and_respects_refusal(monkeypatch):
    monkeypatch.setattr(aws, "is_sso_profile", lambda p: True)
    runner = _Runner()
    with pytest.raises(aws.AuthError):
        aws.ensure_credentials("p", confirm=lambda q: False, opener=_opener(False), runner=runner)
    assert runner.calls == []
    _, account = aws.ensure_credentials("p", confirm=lambda q: True, opener=_opener(False), runner=runner)
    assert account == "123456789012" and len(runner.calls) == 1


@pytest.mark.unit
def test_ensure_credentials_sso_failures(monkeypatch):
    monkeypatch.setattr(aws, "is_sso_profile", lambda p: True)
    with pytest.raises(aws.AuthError, match="not found"):
        aws.ensure_credentials("p", auto_login=True, opener=_opener(False), runner=_Runner(missing=True))
    with pytest.raises(aws.AuthError, match="failed"):
        aws.ensure_credentials("p", auto_login=True, opener=_opener(False), runner=_Runner(code=1))
    with pytest.raises(aws.AuthError, match="Still unauthenticated"):
        aws.ensure_credentials("p", auto_login=True, opener=_opener(False, after_login=False), runner=_Runner())
