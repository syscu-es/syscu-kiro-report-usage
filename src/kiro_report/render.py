"""Render the report document into a single self-contained HTML file."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).parent
ASSETS_DIR = PACKAGE_DIR / "assets"
TEMPLATE = PACKAGE_DIR / "templates" / "report.html"
DEFAULT_BRAND = "SysCu"
_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@dataclass(frozen=True)
class Branding:
    """Name, logos (light/dark theme) and optional embedded font of the report."""

    name: str
    logo_light: tuple[str, bytes] | None  # (mime, bytes)
    logo_dark: tuple[str, bytes] | None
    font: bytes | None


def _read(path: Path) -> bytes:
    return path.read_bytes()


def default_branding(*, embed_font: bool = True) -> Branding:
    """Bundled SysCu branding (logo in both themes and the Figtree font)."""
    return Branding(
        DEFAULT_BRAND,
        ("image/svg+xml", _read(ASSETS_DIR / "logo-light.svg")),
        ("image/svg+xml", _read(ASSETS_DIR / "logo-dark.svg")),
        _read(ASSETS_DIR / "Figtree-Variable.woff2") if embed_font else None,
    )


def load_branding(
    name: str | None = None,
    logo: Path | None = None,
    *,
    no_logo: bool = False,
    embed_font: bool = True,
) -> Branding:
    """Branding from CLI options: bundled defaults, overridden by ``name``/``logo``."""
    base = default_branding(embed_font=embed_font)
    if no_logo:
        base = Branding(base.name, None, None, base.font)
    elif logo:
        mime = _MIME.get(logo.suffix.lower())
        if mime is None:
            raise ValueError(f"unsupported logo type {logo.suffix!r}; use svg, png or jpg")
        custom = (mime, _read(logo))
        base = Branding(base.name, custom, custom, base.font)
    return Branding(name or base.name, base.logo_light, base.logo_dark, base.font)


def _data_uri(asset: tuple[str, bytes] | None) -> str:
    if not asset:
        return ""
    mime, raw = asset
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _font_css(font: bytes | None) -> str:
    if not font:
        return ""
    b64 = base64.b64encode(font).decode()
    return ("@font-face{font-family:Figtree;src:url(data:font/woff2;base64," + b64 +
            ') format("woff2");font-weight:300 900;font-display:swap}')


def render(
    data: dict[str, Any],
    branding: Branding | None = None,
    lang: str = "en",
    template: Path = TEMPLATE,
) -> str:
    """Fill the HTML template. ``</`` is escaped so data can never close the script tag."""
    brand = branding or default_branding()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.read_text(encoding="utf-8")
    replacements = {
        "__FONT_CSS__": _font_css(brand.font),
        "__BRAND_NAME__": brand.name.replace("<", "&lt;").replace(">", "&gt;"),
        "__LOGO_LIGHT__": _data_uri(brand.logo_light),
        "__LOGO_DARK__": _data_uri(brand.logo_dark),
        "__LANG__": "es" if lang == "es" else "en",
        "__DATA__": payload,  # last: the payload must not be re-scanned for placeholders
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html
