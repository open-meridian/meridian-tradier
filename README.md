# meridian-tradier

Tradier's US equity and ETF market data in an [Open Meridian](https://open-meridian.dev)
deployment, as a data plugin (the `data` role): daily closes and bars, live prices and
quotes, and its time and sales as trades, put into the deployment's lake for
the plugins that value and show a book.

It is the second half of the retail pair, beside
[meridian-alpaca](https://github.com/open-meridian/meridian-alpaca): both
pass the same suite of the SDK, unchanged. Tradier is also a broker; this
repository is named for the vendor so that a `custody` or `connectivity` role can
arrive here later without a rename.

**Status:** 0.3.0, on open-meridian 0.24.0 (contract 20), proven locally
against core v20's runtime and plugin harness, neither released yet. Not
released.

## What it serves

| Dataset | What | From | Arrives | Default terms |
|---|---|---|---|---|
| `daily` | each listing's close and daily bar (open, high, low, close, volume) for a business date, New York's day ending at the 16:00 close | Tradier's daily history, consolidated across exchanges | pulled when a reader's read is wanted; pushed once a session's close is final, for the listings it has served | kept; personal use |
| `live` | the last trade's price (`last`), the best bid and ask; the best bid and offer as a quote, with its sizes in shares | Tradier's quotes, consolidated from every exchange, real time for a Tradier Brokerage account holder | pulled for a read; while a standing want stands, prices kept current once a minute and quotes streamed, at most one a second per listing | served, not kept; personal use |
| `trades` | each time and sale with the platform's trade attributes and Tradier's sequence number | Tradier's stream | streamed for the listings under a standing want | kept two days; personal use |

- A daily price is keyed by a plain date, Tradier's own `date`. A day still
  forming is recorded and restated under the same row as it fills, until
  its close is final. Tradier states no VWAP or trade count for a day.
- A last price names the exchange its trade printed on, by Tradier's own
  code, resolved to the deployment's venue master; the best bid and ask are
  consolidated and name none. Tradier's codes are not yet in the venue
  master, so each is reported as a venue the deployment does not hold, kept
  as reported on the row, and named once curation adds it.
- One spelling of a share class: Tradier spells Berkshire's B shares
  `BRK/B`; the plugin names the listing `BRK.B`, as meridian-alpaca does,
  and asks Tradier in its own spelling.
- Tradier states quote sizes in hundreds of shares; a quote carries them
  converted to shares.
- Every number is exact, read from Tradier's own text and never through a
  float. A value that does not convert is counted on the Datasets page,
  never recorded.
- Every response, and every stream event, is kept first as a raw record in
  the storage the deployment grants the plugin, without the token or a
  session's ID; every row names the one it came from.
- Each row under its own record's key: where the deployment holds two
  records of one listing (one Tradier's, one a custodian's, not yet merged),
  each record's rows are its own, the key naming the record
  (`SPY:1d:2026-10-08@LCL-...`), never one recorded over the other. A day
  read again unchanged is kept unchanged. Rows recorded before 0.2.0 keep
  their keys and stand beside the new ones.
- Not here: options, mutual funds (Tradier documents them as not
  available).

## Trades and quotes, streamed

- **What is streamed** is what the lake keeps current: the listings under a
  standing want, of the live prices, the quotes or the trades, and nothing
  while there is none. A session is made with the token and the WebSocket
  opened with it; the events are each time and sale and each quote.
- **A trade's attributes** come from what Tradier documents: a print in the
  regular session with no flag may set every statistic; one before or after
  it is an extended-hours trade, counted in the volume only. Tradier does
  not document its flags, so a flag (or a correction) is kept as reported,
  its eligibilities not known, and counted for a person to map. No
  aggressor: Tradier never says which side took liquidity.
- **A cancel** is the trade's next version where it names a print recorded
  here by its sequence number; one naming no print recorded here is counted
  and not sent.
- **Reconnect.** A stream that breaks is opened again with a new session, a
  second later and then doubling to a minute, and subscribed again from
  what is wanted. The gap between two sessions is not filled: Tradier's
  time and sales history names no print by its sequence number, so reading
  it again would record trades twice. Each reconnect is counted on the
  Connection page.
- **A restart's gap is not backfilled** either (contract v20 has a data
  plugin backfill a restart's gap from its source's history where the
  history allows): the lake delivers each standing want again to a plugin
  started anew and it streams again, but what was traded while it was
  stopped is not read, for the same reason. Datasets says so.
- **Streamed only:** a reader's range of trades is not Tradier's to answer,
  for the same reason, and is declined, not covered.
- **The suite.** Six of its cases are not presented, each with why: a
  currency's rate and a crypto asset's price (kinds Tradier's stock data never
  publishes), the two about the side that took liquidity (a field,
  `Trade.aggressor`, Tradier never states), an odd lot (a characteristic no
  documented flag says), and a restart's gap backfilled (above).

**Instruments another source named.** The lake asks for a price by the
deployment's own instrument ID. An instrument known to the deployment only
by another source's identifiers -- a custodian's symbol and CUSIP, as the
book holds it -- is read from its record, priced under the listing's one
spelling, and Tradier's symbol is added to the record. Only a record
carrying no symbol is declined, not covered. On a runtime from before
contract 18 let a data plugin read an instrument's record, such an instrument is
declined, and the Datasets page says why.

## Tradier's terms, summarised

Not legal advice: read Tradier's own terms before relying on this.

- "Unless you are a Tradier Partner, Tradier APIs are entitled for **personal
  use only**."
- Market data goes only to **active Tradier Brokerage account holders**, and
  is **never redistributed** to anyone without one.
- An account holder's market data is real time and consolidated from every
  exchange, at no charge for API access, up to 120 requests a minute per
  token; the developer sandbox is delayed 15 minutes.

So each dataset's default licence is one person's (`personal_use`), shown and
used by its holder. The deployment admin confirms or changes it on the Data
sources page, which warns when more than one person can read a plugin
entitled to a one-person dataset. Neither this plugin nor its documentation
says a deployment meets Tradier's terms: the licence records what the admin
entered.

## Entering the token

The plugin needs a Tradier Brokerage account's personal API access token;
for an individual it does not expire.

1. In your Tradier Brokerage account, open the **API** settings page and copy
   your access token.
2. In the deployment, open the plugin under **Manage**, then **Settings**.
3. Choose the **Environment**, the first setting: **Live**, Tradier's API
   with your brokerage account's token, or **Sandbox**, Tradier's developer
   sandbox (`sandbox.tradier.com`), for testing, whose data is delayed 15
   minutes and which does not stream; live prices are still kept current
   once a minute. Then the one token, for the environment chosen: your
   brokerage account's API access token on Live, a developer sandbox token
   on Sandbox. The plugin's pages name it by the environment ("API access
   token" or "Sandbox access token") and say which environment the data
   comes from; the Settings form calls it **Access token**, saying it must
   match Environment. It is a secret setting: once saved it is never shown again,
   logged, put on a page or sent anywhere but Tradier. Until 0.3.0 the
   sandbox was a switch, `sandbox`; a deployment that had it on chooses
   Sandbox, and its token carries over, nothing re-entered.
4. Open **Connection**: under **Key** it says the mode (Live or Sandbox),
   whether the token is set (never its value), whether Tradier answered,
   and whether its quotes are real time; on the sandbox, "Tradier's
   developer sandbox: delayed 15 minutes, no streaming", and **Stream**
   says "Does not stream". With no token, "No key yet", linking to
   Settings. **Datasets** names the host asked.
5. On the deployment's **Data sources** page, license `daily`, `live` and
   `trades`,
   and entitle the plugins that read prices.

## Checking it live

The live check is the account holder's own, with their own token, on their
own machine; CI never runs it.

1. `make live` asks for the token at a prompt that does not echo, and hands
   it to a container on its standard input. It prints whether Tradier
   answered, a week of SPY's and BRK/B's closes, their quotes with their sizes
   as Tradier states them (in hundreds), twenty seconds of Tradier's stream
   for them (the flags and sessions its time and sales carried), and
   `key_in_raw_records: false`; never the token. What Tradier answered stays in `recordings/`, which git
   ignores. `make live SANDBOX=1` asks the sandbox with a developer sandbox
   token instead.
2. `make e2e-recorded RECORDED=recordings/<when>` replays that recording
   through the e2e on core's plugin harness.
3. On a development deployment, with the plugin launched and the token
   entered (above): Connection's Mode says **Live**, the Summary's
   Connection figure **Answering**, quotes real time; after a
   reader asks for a close, Datasets counts it recorded; after a reader asks
   for a listing's latest quote, Connection's **Stream** says it streams that
   listing, and Datasets counts its trades and quotes.

## Building it

    make ci-local        lint, the tests (the SDK's data suite among them), meridian plugin check, the image, and the e2e
    make e2e             the plugin on core's plugin harness, on sample data, with no token (e2e/run.py)
    make preview         the pages on sample data, for a browser beside the kit
    make install-hooks   push runs ci-local first

Everything runs in containers; the host needs Docker and Python 3 for the
e2e's runner. `docs/` is the plugin's documentation, a draft.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Ideas and bug
reports are welcome as issues; see [CONTRIBUTING.md](CONTRIBUTING.md).
