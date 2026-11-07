"""IAM Identity Center lookups (user id -> user name)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from collections.abc import Callable


def discover_identity_store(session: Any, region: str) -> str | None:
    """Return the Identity Store id of the first Identity Center instance, if any."""
    instances = session.client("sso-admin", region_name=region).list_instances()["Instances"]
    return instances[0]["IdentityStoreId"] if instances else None


def resolve_names(
    session: Any,
    store_id: str,
    region: str,
    user_ids: list[str],
    warn: Callable[[str], None] = lambda _msg: None,
) -> dict[str, str]:
    """Map user ids to Identity Center user names; unresolved ids map to a short prefix."""
    client = session.client("identitystore", region_name=region)

    def one(uid: str) -> tuple[str, str]:
        try:
            return uid, client.describe_user(IdentityStoreId=store_id, UserId=uid)["UserName"]
        except Exception as exc:  # deleted user or missing permission: never abort the report
            warn(f"  could not resolve user {uid[:8]}: {exc}")
            return uid, uid[:8]

    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, user_ids))
