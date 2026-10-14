"""Custody's pages, from 0.7.0 (spec/plugin-pages-follow-their-role,
`meridian.roles.custody`), each the same answer as its tool. Connectivity's
Trading page (trading_page.py) stays where it is; Raw records, there too,
serves both roles.

- Account links (`/links`, Manage; custody): `read_account_links`, linking
  with `link_account` (checked by `check_link_account`) each account the
  token reaches to one of the accounts a deployment admin granted this
  instance, or, for a deployment admin, to a new account created and linked
  in one step (W6.4), its custodian and type pre-filled: Tradier, and the
  account's type as Tradier states it.
- Statements (`/statements`, Open and View; custody): `read_statements`,
  each account's state at Tradier and the day its last statement is as of.
- History (`/history`, Open and View; custody): `read_account_activities`,
  each account's history as Tradier reported it, the latest first.

Statements and History show an account only to a person who may read the
account it is linked to.
"""

from __future__ import annotations

import meridian
from meridian.roles import custody

from .custody import account_kind, institution
from .page import current, pages
from .records import LinkAsked

LINKS = "/links"
STATEMENTS = "/statements"
HISTORY = "/history"
CHECK = "/check"
WHAT = "This plugin brings Tradier accounts into this deployment"
#: The type a new account is pre-filled with, by the kind Tradier's says.
ACCOUNT_TYPES = {
    meridian.AccountKind.ACCOUNT_KIND_CASH: "cash",
    meridian.AccountKind.ACCOUNT_KIND_MARGIN: "margin",
    meridian.AccountKind.ACCOUNT_KIND_RETIREMENT: "retirement",
}


def _reached() -> list[str]:
    syncer = current().syncer
    return sorted(syncer.status.accounts) if syncer is not None else []


def _account_type(number: str) -> str:
    syncer = current().syncer
    profile = syncer.profiles.get(number, {}) if syncer is not None else {}
    kind, _ = account_kind(profile)
    return ACCOUNT_TYPES.get(kind, "")


def _paper() -> bool:
    config = current().config
    return config.paper and not config.sample_data


async def _links_read(request: meridian.Request) -> custody.AccountLinksRead:
    granted = await request.plugin.read_accounts_for_linking(acting_for=request.caller.header)
    return custody.AccountLinksRead(
        external_accounts=[
            custody.ExternalAccountRead(
                number,
                f"Tradier {number}",
                ", ".join(filter(None, (institution(_paper()), _account_type(number)))),
            )
            for number in _reached()
        ],
        accounts=[custody.AccountRead(each.account_id, each.name) for each in granted.accounts],
        links=[
            custody.LinkRead(link.external_account_id, link.account_id, link.account_name)
            for link in current().scope.links
        ],
    )


@pages.page(
    LINKS,
    "Account links",
    levels="admin",
    roles="custody",
    answers=custody.AccountLinksRead,
    name="read_account_links",
    description=(
        "Each Tradier account the token reaches, by its number; the deployment's accounts a "
        "deployment admin granted this plugin to link to (nothing by default); and the links "
        "between them."
    ),
)
async def account_links(request: meridian.Request) -> meridian.Response:
    return pages.answer("account_links.html", await _links_read(request), action=LINKS)


def _asked(request: meridian.Request) -> LinkAsked:
    link: LinkAsked = request.params
    if link.external_account_id not in _reached():
        pages.refuse("the token reaches no such account", ("external_account_id", "not reached"))
    return link


@pages.route(
    LINKS + CHECK,
    levels="admin",
    roles="custody",
    methods=["POST"],
    params=LinkAsked,
    answers=custody.LinkRead,
    reads=True,
    name="check_link_account",
    description=(
        "Check link_account without linking: the external account is one the token reaches, "
        "and the account is one granted to this plugin, or a new one a deployment admin "
        "would create."
    ),
)
async def check_link_account(request: meridian.Request) -> meridian.Response:
    link = _asked(request)
    if link.intent == "create" or link.new_account_name:
        if not request.caller.deployment_admin:
            pages.refuse(
                "only a deployment admin creates an account", ("new_account_name", "not allowed")
            )
        return pages.answer(
            "account_links.html",
            custody.LinkRead(link.external_account_id, "", link.new_account_name),
        )
    granted = await request.plugin.read_accounts_for_linking(acting_for=request.caller.header)
    names = {each.account_id: each.name for each in granted.accounts}
    if link.account_id and link.account_id not in names:
        pages.refuse("the account is not granted to this plugin", ("account_id", "not granted"))
    return pages.answer(
        "account_links.html",
        custody.LinkRead(link.external_account_id, link.account_id, names.get(link.account_id, "")),
    )


@pages.route(
    LINKS,
    levels="admin",
    roles="custody",
    methods=["POST"],
    params=LinkAsked,
    name="link_account",
    checked_by="check_link_account",
    accounts=["account_id"],
    description=(
        "Link a Tradier account to one of the accounts granted to this plugin (W6.4), to a "
        "new account a deployment admin creates and links in one step, or, with neither, "
        "remove its link; one not granted is refused."
    ),
)
async def link_account(request: meridian.Request) -> meridian.Response:
    link = _asked(request)
    creating = link.intent == "create" or bool(link.new_account_name)
    made = await request.plugin.link_external_account(
        external_account_id=link.external_account_id,
        account_id="" if creating or link.intent == "unlink" else link.account_id,
        new_account_name=link.new_account_name if creating else "",
        new_account_custodian=(link.new_account_custodian or institution(_paper()))
        if creating
        else "",
        new_account_type=(link.new_account_type or _account_type(link.external_account_id))
        if creating
        else "",
        acting_for=request.caller.header,
    )
    if request.tool_name:
        return pages.answer(
            "account_links.html", custody.LinkRead(made.external_account_id, made.account_id)
        )
    said = (
        f"Created {link.new_account_name} and linked {link.external_account_id} to it."
        if creating
        else f"Linked {link.external_account_id}."
    )
    return pages.answer("account_links.html", await _links_read(request), action=LINKS, notice=said)


# ── Statements and History ─────────────────────────────────────────────────


def _readable(request: meridian.Request) -> dict[str, str]:
    """The external accounts linked to an account the person may read, each
    by the name of the account it is linked to."""
    allowed = request.caller.read_for("custody")
    return {
        link.external_account_id: link.account_name or link.account_id
        for link in current().scope.links
        if link.account_id in allowed
    }


@pages.page(
    STATEMENTS,
    "Statements",
    levels=["write", "read"],
    roles="custody",
    answers=custody.StatementsRead,
    name="read_statements",
    description=(
        "Each Tradier account linked to one the person may read: its custodian, the day its "
        "last statement is as of, and its state at Tradier."
    ),
)
async def statements(request: meridian.Request) -> meridian.Response:
    syncer = current().syncer
    held = syncer.status.accounts if syncer is not None else {}
    readable = _readable(request)
    said = custody.StatementsRead(
        statements=[
            custody.StatementRead(
                account=readable[number],
                custodian=institution(_paper()),
                as_of=status.statement_as_of,
                state=f"{status.statement_state or 'Not read yet'} ({status.state})",
            )
            for number, status in sorted(held.items())
            if number in readable
        ]
    )
    return pages.answer("statements.html", said, what=WHAT)


@pages.page(
    HISTORY,
    "History",
    levels=["write", "read"],
    roles="custody",
    answers=custody.HistoryRead,
    name="read_account_activities",
    description=(
        "Each Tradier account's history as Tradier reported it, where it is linked to one the "
        "person may read: each activity's kind, trade date, instrument, units, amount and "
        "description, the latest first."
    ),
)
async def history(request: meridian.Request) -> meridian.Response:
    syncer = current().syncer
    held = syncer.status.accounts if syncer is not None else {}
    readable = _readable(request)
    activities = []
    for number, status in sorted(held.items()):
        if number not in readable:
            continue
        for converted, instrument in status.activities:
            activities.append(
                custody.ActivityRead(
                    account=readable[number],
                    external_activity_id=converted.external_activity_id,
                    kind=meridian.ActivityKind.Name(converted.kind)
                    .removeprefix("ACTIVITY_KIND_")
                    .replace("_", " ")
                    .lower(),
                    trade_date=converted.trade_date,
                    instrument_id=instrument,
                    units="" if converted.units is None else str(converted.units),
                    amount="" if converted.amount is None else str(converted.amount.amount),
                    description=converted.description,
                )
            )
    return pages.answer("history.html", custody.HistoryRead(activities=activities), what=WHAT)
