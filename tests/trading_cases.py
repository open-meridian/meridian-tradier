"""Tradier's connectivity work run against the suites' recorder: the plugin's
SDK Trader (meridian.roles.connectivity) over its own venue adapter (venue.py) and brokerage
API client (broker.py), speaking to the simulated brokerage
(synthetic_broker.py); only the sidecar is stood in for by the recorder.

Shared by the connectivity suite's test and the trading tests. SIMULATED
ONLY: nothing here reaches Tradier, its developer sandbox or any brokerage.
"""

from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.connectivity import Venue, testing
from meridian.roles.connectivity.testing import ACCOUNT, CALENDAR, INSTRUMENT, NOW, asking, clock
from meridian.suites import Recorder

from tradier.broker import Broker
from tradier.kinds import Store
from tradier.synthetic_broker import ACCOUNT_NUMBER, SyntheticBroker
from tradier.vendor import SANDBOX, RateLimiter
from tradier.venue import TradierVenue

__all__ = ["ACCOUNT", "CALENDAR", "INSTRUMENT", "NOW", "asking", "clock"]

Producer = Callable[[Recorder], Awaitable[None]]

CODE = ACCOUNT_NUMBER


def placement(pid: str = "PLC-01JAE00000000000000000001", **kw: Any) -> ops.Placement:
    """A placement to this plugin's instance, in its account."""
    kw.setdefault("instance", "tradier")
    kw.setdefault("code", CODE)
    return testing.placement(pid, **kw)


def scope(*codes: str, instance: str = "tradier") -> Any:
    return testing.scope(*codes, instance=instance)


class Rig(testing.Rig):
    """The SDK's Trader over the recorder and this plugin's own adapter and
    client, speaking to the simulated brokerage; trading enabled on its
    account."""

    instance = "tradier"
    code = CODE
    source = "tradier"

    def connect(self, broker: Any) -> Venue:
        self.brokerage = broker or SyntheticBroker(clock)
        self.store = Store(Path(tempfile.mkdtemp()))
        self.broker = Broker(
            self.store,
            None,
            SANDBOX,
            send=self.brokerage,
            limiter=RateLimiter(per_minute=6_000_000, sleep=lambda _: None),
            now=clock,
            keyless=True,
            synthetic=True,
        )
        return TradierVenue(self.broker)


async def placed_and_filled(recorder: Recorder) -> None:
    """A placement of 10 placed and filled at the simulated brokerage: 4, then
    the rest, each with the date read's settlement date."""
    rig = Rig(recorder)
    held = placement()
    rig.holds(held)
    await rig.hear(held)
    await rig.poll(2)
