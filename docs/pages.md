# Its pages

Both pages are the data role's, the same on every data plugin, under Manage
for an admin of the plugin. Neither shows a price: prices are read by the
plugins entitled to them. Each page is also a tool an agent can call through
your deployment's MCP connection, answering exactly what the page shows,
under the same names on every data plugin.

## Connection (`read_connection`)

- **Key:** the mode (Live, Sandbox, Sample data or No key; on the sandbox,
  Tradier's developer sandbox, delayed 15 minutes, no streaming); whether
  the token for the environment chosen is set, never its value; what
  Tradier serves your token (daily history, quotes in real time or delayed
  on the sandbox, the stream), and what it does not. With no token, "No key
  yet", linking to Settings.
- **Limits and use:** the plugin spends at most 60 calls a minute, half of
  Tradier's 120 for market data; calls since it started, any answered "too
  many requests" and waited out; the last call and the last error.
- **Stream:** how many sessions stream, or "Does not stream" on the
  sandbox; then Tradier's own rows: its state, how many listings since
  when, its reconnects (each a gap Tradier's history cannot fill) and
  messages.

## Datasets (`read_datasets`)

- **Served:** each dataset as its catalogue declares it: what it serves, how
  its rows arrive, its day, its default terms and whether a deployment admin
  has licensed it, whether Tradier serves your token it, and what it
  recorded and declined since the plugin started, and when it last
  recorded; the feed and host each reads (Tradier's column).
- **Wants:** the standing wants it keeps current, the latest first: of
  which dataset, asking what, for how many subjects, what each was answered
  with, and whether its listings are streamed. With none, "No wants yet".
- **Subjects:** whether the deployment lets the plugin read an instrument's
  record.
- **Kept current** (Tradier's): how many listings it knows and streams, and
  days still forming. A restart's or a reconnect's gap is not caught up.
