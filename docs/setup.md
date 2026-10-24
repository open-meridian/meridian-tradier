# Setting it up

Each step by an admin of the plugin, on its roles as each says. The plugin
must already be launched, its roles approved by a deployment admin. The
steps follow the data and custody roles' first-use paths; what is Tradier's own
is below.

## 1. The access token

In your Tradier Brokerage account, open the API settings page and copy your access token; for the sandbox, a developer sandbox token.

## 2. Enter it

**Manage → Settings.**

1. **Environment**, first: **Live** is Tradier's API with your brokerage account's token; **Sandbox** is Tradier's developer sandbox, for testing, delayed 15 minutes and not streaming, trading a paper account with simulated money. It is Sandbox until a person chooses Live. Agents may place orders only on Sandbox.
2. The **Access token** for the environment chosen: the brokerage account's API access token on Live, a developer sandbox token on Sandbox. Secret settings: once saved
   they are never shown again, logged, put on a page or sent anywhere but
   Tradier.
3. **Read every** and **Stale after**: how often the account is read (300
   seconds by default), and how long it may go unanswered before it is
   reported stale (36 hours).

**Connection** then says under Key whether each part is set, never its
value, and whether Tradier answered. With none, "No key yet", linking to
Settings.

## Account currency

Tradier states no currency for any holding or amount. On **Account currency**, a tab under Manage, the plugin's admin gives each linked account's currency as an ISO code, or one row for every account. Every amount then carries it, supplied by that person; until a row covers an account, its statements and activity are not reported.

## 3. License and entitle its datasets

A deployment admin, on the deployment's **Data sources** page, licenses
`daily`, `live` and `trades`, each starting from Tradier's terms, one person's
use, and entitles the plugins that read prices, trades and quotes. Nothing
is read from Tradier until a plugin entitled to a dataset asks for a price.

## 4. Link the account

A deployment admin grants the plugin the accounts it may link to. Its admin
links Tradier's account to one of them on **Account links**, under Manage, or a
deployment admin creates a new account and links it in one step. Then a
deployment admin grants people read or write on it, so they see its
statements under View or Open.

## 5. Trading, only if you place orders through it

A deployment admin makes the plugin available to the desk's execution
plugin, whose admin links it and maps a book account to the account's
venue account code, shown on **Connection**. A new account is read-only:
every order on it is rejected as unsupported, nothing sent, until the
connectivity role's admin presses **Enable trading** there. Its catalogue
is then published: `market` for the day; `limit`, `stop` and `stop_limit`,
each day or GTC. Tradier takes no good-till-date order and no request for
quote: every order is placed directly (DMA). Its pre- and post-market
sessions have no counterpart.

## Sample data

On a development deployment, **Sample data** answers from built-in made-up
data instead of Tradier, and trades with a simulated brokerage. Nothing reaches
Tradier.
