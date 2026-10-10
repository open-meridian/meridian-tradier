"""What the plugin needs from the deployment, declared as settings (W4.7, W6.11).

Tradier's market data API takes a Tradier Brokerage account's personal API
access token, from the account's API settings page; for an individual,
"your tokens never expire". It is a **secret setting**: an admin of the
plugin enters it in the dashboard's settings form, and it is never read
back, displayed, logged, reported or kept. It reaches this process in
`meridian.Settings` and nowhere else. `Credentials` keeps it out of its
repr; vendor.py sends it as a bearer token and keeps it in no raw record;
the Connection page says whether it is set, never what it is.

`synthetic`, a developer's setting (shown only on a development deployment),
serves the built-in synthetic exchange (synthetic.py) instead of calling
Tradier, with no token: what the e2e and a first look use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import meridian

TOKEN = "tradier_access_token"
SYNTHETIC = "synthetic"

DECLARED: tuple[meridian.Setting, ...] = (
    meridian.Setting(
        TOKEN,
        str,
        required=True,
        secret=True,
        label="API access token",
        description=(
            "From your Tradier Brokerage account's API settings page. A personal "
            "token does not expire."
        ),
    ),
    meridian.Setting(
        SYNTHETIC,
        bool,
        default=False,
        developer=True,
        label="Synthetic",
        description=(
            "Serve the built-in synthetic Tradier responses instead of calling Tradier, "
            "with no token. For development and tests only."
        ),
    ),
)


@dataclass(frozen=True)
class Credentials:
    """What Tradier is called with. Never in a repr, a log line, a page or a
    raw record."""

    token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("a Tradier access token is needed")

    def headers(self) -> dict[str, str]:
        """Tradier's authentication header, for the request alone."""
        return {"Authorization": f"Bearer {self.token}"}

    def secrets(self) -> tuple[str, ...]:
        """The values never to be kept anywhere, for raw records to look for."""
        return (self.token,)


@dataclass(frozen=True)
class Config:
    """The settings as the plugin uses them: the token, if given, whether it
    is set (never its value), and synthetic mode."""

    credentials: Credentials | None = None
    token_set: bool = False
    synthetic: bool = False

    @property
    def ready(self) -> bool:
        """Whether there is something to ask: synthetic, or the token."""
        return self.synthetic or self.credentials is not None


def config_from(values: Mapping[str, object]) -> Config:
    """The settings as delivered, typed."""
    token = str(values.get(TOKEN) or "")
    return Config(
        credentials=Credentials(token) if token else None,
        token_set=bool(token),
        synthetic=values.get(SYNTHETIC) is True,
    )
