# meridian-tradier

Tradier's US equity and ETF market data in an [Open Meridian](https://open-meridian.dev)
deployment, as a `dgm` plugin: daily closes and bars, and live prices, put
into the deployment's lake for the plugins that value and show a book.

It is the second half of the retail pair, beside
[meridian-alpaca](https://github.com/open-meridian/meridian-alpaca): both
pass the same suite of the SDK, unchanged. Tradier is also a broker; this
repository is named for the vendor so that a `custody` or `ccm` role can
arrive here later without a rename.

**Status:** built on open-meridian 0.22.0 (contract 18), which is not yet on
PyPI. Until it is, this repository's CI is red: every job installs the SDK
it pins, and a developer's machine builds it from the sibling
meridian-python checkout instead. Not released.

## What it serves

| Dataset | What | From | Arrives | Default terms |
|---|---|---|---|---|
| `daily` | each listing's close and daily bar (open, high, low, close, volume) for a business date, New York's day ending at the 16:00 close | Tradier's daily history, consolidated across exchanges | pulled when a reader's read is wanted; pushed once a session's close is final, for the listings it has served | kept; personal use |
| `live` | the last trade's price (`last`), the best bid and ask | Tradier's quotes, consolidated from every exchange, real time for a Tradier Brokerage account holder | pulled for a read; kept current once a minute while a standing want stands | served, not kept; personal use |

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
- Tradier states quote sizes in hundreds of shares. A price carries no size,
  so the sizes stay in the raw record until the lake's quotes carry them,
  converted to shares.
- Every number is exact, read from Tradier's own text and never through a
  float. A value that does not convert is counted on the Datasets page,
  never recorded.
- Every response is kept first as a raw record in the storage the deployment
  grants the plugin, without the token; every row names the one it came from.
- Not here: options, mutual funds (Tradier documents them as not
  available), trades and quotes and Tradier's streaming (with the lake's next
  revision).

**One limit of contract 18.** The lake asks for a price by the deployment's
own instrument ID. A `dgm` may resolve its own identifiers to an instrument,
but may not read an instrument's record, so it can name to Tradier only the
listings it resolved itself by their symbol. An instrument known to the
deployment only by another source's identifier (a custodian's symbol, say)
is declined, not covered, and the Datasets page says why. The code already
reads an instrument's record where the deployment allows it.

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
3. Enter the **API access token**. It is a secret setting: once saved it is
   never shown again, logged, put on a page or sent anywhere but Tradier.
4. Open **Connection**: it says whether the token is set (never its value),
   whether Tradier answered, and whether its quotes are real time.
5. On the deployment's **Data sources** page, license `daily` and `live`,
   and entitle the plugins that read prices.

## Checking it live

The live check is the account holder's own, with their own token, on their
own machine; CI never runs it.

1. `make live` asks for the token at a prompt that does not echo, and hands
   it to a container on its standard input. It prints whether Tradier
   answered, a week of SPY's and BRK/B's closes, their quotes with their sizes
   as Tradier states them (in hundreds), and `key_in_raw_records: false`;
   never the token. What Tradier answered stays in `recordings/`, which git
   ignores. `make live SANDBOX=1` asks the sandbox with a developer sandbox
   token instead.
2. `make e2e-recorded RECORDED=recordings/<when>` replays that recording
   through the e2e on core's plugin harness.
3. On a development deployment, with the plugin launched and the token
   entered (above): Connection says **Connected**, quotes real time; after a
   reader asks for a close, Datasets counts it recorded.

## Building it

    make ci-local        lint, the tests (the SDK's dgm suite among them), meridian plugin check, the image, and the e2e
    make e2e             the plugin on core's plugin harness, synthetic, with no token (e2e/run.py)
    make preview         the pages on synthetic data, for a browser beside the kit
    make install-hooks   push runs ci-local first

Everything runs in containers; the host needs Docker and Python 3 for the
e2e's runner. `docs/` is the plugin's documentation, a draft.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Ideas and bug
reports are welcome as issues; see [CONTRIBUTING.md](CONTRIBUTING.md).
