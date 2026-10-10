# Setting it up

You need a Tradier Brokerage account's personal API access token. For an
individual it does not expire.

1. **Get the token.** In your Tradier Brokerage account, open the API
   settings page and copy your access token.
2. **Add the plugin** to your deployment and approve what it asks for: the
   `dgm` role, and storage for Tradier's responses.
3. **Enter the token.** Open the plugin under Manage, then Settings, and
   enter the API access token. It is secret: once saved it is never shown
   again.
4. **Check the connection.** The Connection page should say Connected, with
   quotes in real time.
5. **License and entitle.** On the deployment's Data sources page, license
   `tradier:daily` and `tradier:live`. Each starts from Tradier's terms: one
   person's use. Then entitle the plugins that read prices to each dataset.

Nothing is read from Tradier until a plugin entitled to a dataset asks for a
price.
