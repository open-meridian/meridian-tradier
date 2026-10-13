"""What the plugin needs from the deployment, declared as settings (W4.7, W6.11).

Tradier's market data API takes a Tradier Brokerage account's personal API
access token, from the account's API settings page; for an individual,
"your tokens never expire". It is a **secret setting**: an admin of the
plugin enters it in the dashboard's settings form, and it is never read
back, displayed, logged, reported or kept. It reaches this process in
`meridian.Settings` and nowhere else. `Credentials` keeps it out of its
repr; vendor.py sends it as a bearer token and keeps it in no raw record;
the Connection page says whether it is set, never what it is.

The data role's common settings, in its order
(spec/plugin-pages-follow-their-role, Q12 as amended 2026-10-10), and from
0.6.0 connectivity's too, each naming the two roles it serves:

- `environment` first, a required choice (`meridian.environment`): `live`,
  Tradier's API with a brokerage account's token, or `sandbox`, Tradier's
  developer sandbox (sandbox.tradier.com), for testing, its data delayed 15
  minutes and with no stream. Before 0.3.0, `sandbox`, a switch. From 0.6.0
  it is also the account connectivity trades: on `live` the brokerage
  account's, real money; on `sandbox` the developer sandbox's paper account,
  simulated money.
- the token, one required secret, `tradier_access_token`, for whichever
  environment is chosen, and for both roles (the same token trades): the
  brokerage account's API access token on `live`, a developer sandbox token
  on `sandbox` (the product owner, 2026-10-11, option B: one token, so which
  source a dataset comes from is never in doubt). Its value carries over
  from 0.2.x unchanged. The plugin's own pages name it by the environment --
  "API access token" or "Sandbox access token" -- and say which environment
  the data comes from; core's Settings form shows the one label the
  declaration carries, a neutral "Access token", so it never names the wrong
  environment.
- `sample_data`, a developer's setting (`meridian.sample_data`, shown
  only on a development deployment), serving the built-in recorded exchange
  (synthetic.py) instead of calling Tradier, with no token: what the e2e
  and a first look use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import meridian

ENVIRONMENT = "environment"
LIVE, SANDBOX = "live", "sandbox"
TOKEN = "tradier_access_token"
SAMPLE_DATA = "sample_data"
#: What the plugin says of the sandbox, plainly, wherever it says which host.
SANDBOX_SAID = "Tradier's developer sandbox: delayed 15 minutes, no streaming"
#: The roles each setting serves: both of them.
EVERY_ROLE = ("data", "connectivity")
#: What connectivity says of each environment, wherever it says which.
SAID = {
    LIVE: "Live: Tradier Brokerage's account, real money",
    SANDBOX: "Paper: Tradier's developer sandbox, simulated money",
}


@meridian.settings
class Declared:
    """The settings as declared, in the data role's order: one typed class,
    the SDK's form, which `connect` and the declaration register."""

    environment: str = meridian.environment(
        description=(
            "Live: Tradier's API, with a Tradier Brokerage account's token, its orders real. "
            "Sandbox: Tradier's developer sandbox, for testing, its data delayed 15 minutes "
            "and not streamed, its orders paper trading with simulated money."
        ),
        roles=EVERY_ROLE,
    )
    tradier_access_token: str = meridian.setting(
        "Access token",
        required=True,
        secret=True,
        roles=EVERY_ROLE,
        description=(
            "Your Tradier API access token for Live, or a developer sandbox token for "
            "Sandbox: it must match Environment."
        ),
    )
    sample_data: bool = meridian.sample_data(
        roles=EVERY_ROLE,
        description=(
            "Answer from built-in made-up data instead of Tradier, and trade with a simulated "
            "brokerage, changing nothing else the plugin does. Development deployments only."
        ),
    )


DECLARED = Declared
#: Each setting it declares, in its order.
SETTINGS: tuple[meridian.Setting, ...] = Declared.declared()  # type: ignore[attr-defined]


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
    """The settings as the plugin uses them: the environment, the token, if
    given, whether it is set (never its value), and sample data."""

    credentials: Credentials | None = None
    token_set: bool = False
    environment: str = LIVE
    sample_data: bool = False

    @property
    def on_sandbox(self) -> bool:
        """Whether Tradier's developer sandbox is asked: sample data asks
        nothing, so it wins."""
        return self.environment == SANDBOX and not self.sample_data

    @property
    def paper(self) -> bool:
        """Whether the account traded is the sandbox's paper account."""
        return self.environment == SANDBOX

    @property
    def ready(self) -> bool:
        """Whether there is something to ask: sample data, or the token."""
        return self.sample_data or self.credentials is not None


def config_from(values: Mapping[str, object]) -> Config:
    """The settings as delivered, typed: the one token, for the environment
    chosen."""
    environment = SANDBOX if values.get(ENVIRONMENT) == SANDBOX else LIVE
    token = str(values.get(TOKEN) or "")
    return Config(
        credentials=Credentials(token) if token else None,
        token_set=bool(token),
        environment=environment,
        sample_data=values.get(SAMPLE_DATA) is True,
    )
