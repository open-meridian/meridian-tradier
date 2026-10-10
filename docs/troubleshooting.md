# Troubleshooting

| You see | It means | Do |
|---|---|---|
| Connection: **No key** | No access token is set | Enter it in Settings |
| Connection: **Not answering** | Tradier refused the token | Check it on your Tradier account's API settings page, or create a new one and enter it |
| Quotes **delayed** | The token answers from Tradier's sandbox, or the account is not entitled to real time | Use your brokerage account's token |
| Datasets: **declined** grows | A reader asked for a listing the plugin cannot name to Tradier, or a day with no session | See the Datasets page's note; a weekend or holiday has no close |
| Datasets: **unconverted** grows | Tradier sent a value the contract cannot hold exactly | Nothing is recorded for it; the raw response is kept |
| A last price with **no venue** | Your deployment does not hold the exchange Tradier named yet | It is reported to the platform, and named once the venue is held |
| **Last error** names a 429 | Tradier's rate limit was hit and waited out | Nothing; the plugin spends half the limit |
