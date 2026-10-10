# Its pages

Both pages are under Manage, for an admin of the plugin. Neither shows a
price: prices are read by the plugins entitled to them. Each page is also a
tool an agent can call through your deployment's MCP connection, answering
exactly what the page shows.

## Connection (`read_connection`)

- **Mode:** live, synthetic (a developer's built-in exchange) or no key.
- **Token:** whether it is set; never its value.
- **Entitled / Not entitled:** whether Tradier answered the token for its
  daily history and for real-time quotes.
- **Rate limit:** the plugin spends at most 60 calls a minute, half of
  Tradier's 120 for market data; calls since it started, any answered "too
  many requests" and waited out.
- **Last call, last error.**
- **Stream:** whether it is streaming, how many listings, since when; and
  its reconnects, each a gap Tradier's history cannot fill.

## Datasets (`read_datasets`)

- Each dataset: how its rows arrive, its default terms, whether Tradier
  answers the token for it, and what it recorded, restated, declined and
  could not convert since the plugin started.
- **Kept current:** the standing wants, searched and paged: for which
  listings, of which dataset, asking what (prices, quotes or trades), and
  whether they are streamed; how many listings the plugin knows and
  streams; days still forming.
