"""Identity helpers shared by the CUR and activity-report readers."""
from __future__ import annotations

import re

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def normalize_user_id(raw: str) -> str:
    """Return the canonical IAM Identity Center user id.

    The CUR carries ``arn:aws:identitystore:::user/<uuid>`` while the Kiro activity
    report may prefix the uuid (``d-xxxx.<uuid>``). Both reduce to the lowercase uuid;
    anything that does not contain a uuid is returned stripped and lowercased.
    """
    text = (raw or "").strip()
    match = _UUID_RE.search(text)
    return (match.group(0) if match else text).lower()
