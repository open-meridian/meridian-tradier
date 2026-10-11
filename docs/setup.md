# Setting it up

You need a Tradier Brokerage account's personal API access token. For an
individual it does not expire.

1. **Get the token.** In your Tradier Brokerage account, open the API
   settings page and copy your access token.
2. **Add the plugin** to your deployment and approve what it asks for: the
   `data` role (a data plugin), and storage for Tradier's responses.
3. **Choose the environment and enter the token.** Open the plugin under
   Manage, then Settings. Environment comes first: Live, or Sandbox for
   Tradier's developer sandbox (delayed 15 minutes, no streaming). Then
   enter the one token (Access token), for the environment chosen: your API access token
   on Live, a developer sandbox token on Sandbox. It is secret: once saved it is never
   shown again.
4. **Check the connection.** The plugin's Summary says Answering, and its
   Connection page quotes in real time (delayed on the sandbox).
5. **License and entitle.** On the deployment's Data sources page, license
   `tradier:daily`, `tradier:live` and `tradier:trades`. Each starts from
   Tradier's terms: one person's use. Then entitle the plugins that read
   prices to each dataset. The plugin's Datasets page then says each is
   licensed.

Nothing is read from Tradier until a plugin entitled to a dataset asks for a
price.
