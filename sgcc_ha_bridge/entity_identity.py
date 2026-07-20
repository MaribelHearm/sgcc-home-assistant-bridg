"""Stable, privacy-preserving Home Assistant identity helpers."""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


_ENTITY_NAMESPACE = "sgcc-home-assistant-bridge:entity:v2:"


@dataclass(frozen=True)
class LegacyAliasPolicy:
    """Collision-safe ownership for last-four legacy MQTT identities."""

    owners: frozenset[str]
    ambiguous_suffixes: frozenset[str]
    authoritative: bool

    def allows(self, account_no: str) -> bool:
        return self.authoritative and str(account_no or "").strip() in self.owners


def _validated_account_no(account_no: str) -> str:
    value = str(account_no or "").strip()
    if len(value) != 13 or not value.isdigit():
        raise ValueError("a full 13-digit SGCC account number is required for entity identity")
    return value


def account_entity_key(account_no: str) -> str:
    """Return a stable unique key without exposing the full SGCC account number."""
    value = _validated_account_no(account_no)
    digest = hashlib.sha256(f"{_ENTITY_NAMESPACE}{value}".encode("utf-8")).hexdigest()[:10]
    return f"{value[-4:]}_{digest}"


def account_entity_postfix(account_no: str) -> str:
    return f"_{account_entity_key(account_no)}"


def legacy_account_postfix(account_no: str) -> str:
    value = str(account_no or "").strip()
    return f"_{value[-4:]}" if value else ""


def legacy_alias_policy(
    account_nos: Iterable[str],
    *,
    published_account_nos: Iterable[str] | None = None,
    authoritative: bool,
) -> LegacyAliasPolicy:
    """Return legacy alias owners only when a complete account set proves uniqueness.

    Every valid account participates in last-four collision detection, including
    ignored or metadata-only accounts. ``published_account_nos`` limits which of
    the unique accounts may own an alias without weakening that collision check.
    """
    if not authoritative:
        return LegacyAliasPolicy(frozenset(), frozenset(), False)

    valid_accounts: set[str] = set()
    for account_no in account_nos:
        try:
            valid_accounts.add(_validated_account_no(account_no))
        except ValueError:
            continue

    published = valid_accounts
    if published_account_nos is not None:
        published = set()
        for account_no in published_account_nos:
            try:
                value = _validated_account_no(account_no)
            except ValueError:
                continue
            if value in valid_accounts:
                published.add(value)

    suffix_counts = Counter(account_no[-4:] for account_no in valid_accounts)
    ambiguous = frozenset(
        suffix for suffix, count in suffix_counts.items() if count > 1
    )
    owners = frozenset(
        account_no
        for account_no in published
        if suffix_counts[account_no[-4:]] == 1
    )
    return LegacyAliasPolicy(owners, ambiguous, True)


def mqtt_legacy_action(
    mode: str,
    account_no: str,
    policy: LegacyAliasPolicy,
) -> str:
    """Return the publisher action for one account under a validated mode."""
    value = str(account_no or "").strip()
    if not policy.authoritative or mode == "off":
        return "none"
    if mode == "cleanup" or value[-4:] in policy.ambiguous_suffixes:
        return "remove"
    if mode == "compat" and policy.allows(value):
        return "publish"
    return "none"


def mqtt_remove_legacy_on_cleanup(
    mode: str,
    account_no: str,
    policy: LegacyAliasPolicy,
) -> bool:
    """Return whether lifecycle cleanup may tombstone a legacy namespace."""
    if not policy.authoritative or mode == "off":
        return False
    if mode == "cleanup":
        return True
    if mode != "compat":
        return False
    suffix = str(account_no or "").strip()[-4:]
    owned_suffixes = {owner[-4:] for owner in policy.owners}
    return suffix not in owned_suffixes
