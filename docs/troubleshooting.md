# Troubleshooting

## Market data

| You see | It means | Do |
|---|---|---|
| Connection: **No key yet** | No token is set for the environment chosen | Enter it in Settings (the link) |
| Connection: **Not answering** | Tradier refused the token | Check it on your Tradier account's API settings page, or create a new one and enter it |
| Quotes **delayed** | The Environment is **Sandbox** in Settings, or the account is not entitled to real time | Choose Live and enter your brokerage account's token |
| Connection: **Sandbox**, Stream: **Does not stream** | The Environment is **Sandbox**: delayed 15 minutes, no streaming | Nothing, while testing; for live data choose Live and enter your brokerage token |
| Datasets: **declined** grows | A reader asked for a listing the plugin cannot name to Tradier, or a day with no session | See the Datasets page's note; a weekend or holiday has no close |
| Datasets: **unconverted** grows | Tradier sent a value the contract cannot hold exactly | Nothing is recorded for it; the raw response is kept |
| A last price with **no venue** | Your deployment does not hold the exchange Tradier named yet | It is reported to the platform, and named once the venue is held |
| **Last error** names a 429 | Tradier's rate limit was hit and waited out | Nothing; the plugin spends half the limit |
| Stream: **Refused** | Tradier refused the token when the plugin asked for a streaming session | Check the token |
| Stream: **reconnects** grow | The stream dropped; each reconnect is a gap not filled | Nothing to do; if it is constant, check the network |
| Datasets: trades **unconverted** grows | Tradier sent a flag the plugin does not convert (Tradier documents none) | Those trades' eligibilities are not known; the flag is kept as reported |
| Datasets: **Not licensed yet** | No deployment admin has licensed the dataset | Ask a deployment admin to license it on Data sources; the page says so within a minute |

## The account

| You see | It means | Do |
|---|---|---|
| Statements: **needs sign-in** | Tradier refused the access token | Check it at Tradier, or make a new one and enter it in Settings |
| Statements: **disabled** | Tradier says the account is closed or blocked | Raise it with Tradier |
| Statements: **stale** | Tradier has not answered for longer than Stale after | Nothing, usually: the next read catches up |
| An account readers cannot see | It is not linked, or they hold no grant on the account it is linked to | Link it on Account links; a deployment admin grants read or write |

## Orders

| You see | It means | Do |
|---|---|---|
| Every order rejected **unsupported** | Trading is not enabled on the account | The connectivity role's admin enables it on Trading |
| An order type or time in force rejected | Tradier's catalogue does not offer it | Choose one the catalogue lists on Trading |
| A fill waits | It is sent only with its settlement date, from the deployment's date read | Nothing: it is asked about again on each read |
| A fill on no order | An order placed in Tradier's own web app filled | The desk accepts it to an order or answers it DK |
| An agent's order refused as live | The connection is not Demo: Environment is Live, or the session reached Tradier's live host | Agents trade only on Sandbox; a person places live orders |
| Orders **held** | A pause or a stop is in force | Lift it; a stop also cancelled what was working |
