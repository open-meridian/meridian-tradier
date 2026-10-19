"""Custody's pages, from 0.7.0 (spec/plugin-pages-follow-their-role,
`meridian.roles.custody`), each the same answer as its tool; from SDK 0.31.0
the SDK's (`custody.account_pages`), this module supplying what is Tradier's
alone: each account the token reaches, its type as Tradier states it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import meridian
from meridian.roles import custody

from .custody import account_kind, institution
from .page import current, pages

LINKS, STATEMENTS, HISTORY = custody.ACCOUNT_LINKS, custody.STATEMENTS, custody.HISTORY
WHAT = "This plugin brings Tradier accounts into this deployment"
#: The type a new account is pre-filled with, by the kind Tradier's says.
ACCOUNT_TYPES = {
    meridian.AccountKind.ACCOUNT_KIND_CASH: "cash",
    meridian.AccountKind.ACCOUNT_KIND_MARGIN: "margin",
    meridian.AccountKind.ACCOUNT_KIND_RETIREMENT: "retirement",
}


class Source:
    """What Tradier's sync holds, as custody's pages read it."""

    vendor = "Tradier"
    credential = "token"

    def _paper(self) -> bool:
        config = current().config
        return bool(config.paper and not config.sample_data)

    def _status(self, number: str) -> Any:
        syncer = current().syncer
        return syncer.status.accounts.get(number) if syncer is not None else None

    def reached(self) -> Sequence[str]:
        syncer = current().syncer
        return sorted(syncer.status.accounts) if syncer is not None else []

    def account(self, number: str) -> custody.ExternalAccountRead:
        detail = ", ".join(filter(None, (institution(self._paper()), self.account_type(number))))
        return custody.ExternalAccountRead(number, f"Tradier {number}", detail)

    def custodian(self) -> str:
        return institution(self._paper())

    def account_type(self, number: str) -> str:
        syncer = current().syncer
        profile = syncer.profiles.get(number, {}) if syncer is not None else {}
        kind, _ = account_kind(profile)
        return ACCOUNT_TYPES.get(kind, "")

    def statement(self, number: str) -> tuple[str, str] | None:
        status = self._status(number)
        if status is None:
            return None
        return (
            status.statement_as_of,
            f"{status.statement_state or 'Not read yet'} ({status.state})",
        )

    def activities(self, number: str) -> Sequence[tuple[Any, str]]:
        status = self._status(number)
        return [] if status is None else list(status.activities)

    def links(self) -> Sequence[Any]:
        return current().scope.links


# Account links in the plugin's own template (a notice once linked, and a
# plain form per account for a browser without the kit); Statements and
# History in the role's.
custody.account_pages(
    pages,
    Source,
    what=WHAT,
    templates=(
        "account_links.html",
        "meridian/roles/custody/statements.html",
        "meridian/roles/custody/history.html",
    ),
)
