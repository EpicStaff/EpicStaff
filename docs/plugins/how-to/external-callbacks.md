# Receive an external provider's callback

A plugin that connects to another service (Google, GitHub, …) runs that service's OAuth sign-in. The provider's pages
refuse to be framed, so the sign-in opens in a **popup**, and the provider sends the person back to a page of your
plugin with a code. That page has to hand the code to your page inside EpicStaff. The JS SDK does this in two ways:

1. **Through the opener.** The return page posts the result to the page that opened the popup, on your plugin's own
   origin. This is the usual path.
2. **Through your backend (the relay).** Some providers send `Cross-Origin-Opener-Policy`, which cuts the popup off
   from its opener for good. The return page then signs the person in on its own, posts the result to your backend,
   and the page inside EpicStaff asks your backend for it.

You do not choose: give the SDK a relay and it uses whichever path works first.

## What you build

| Piece | Where |
|---|---|
| A button that opens the popup | Your page |
| The provider's redirect URI: a page of your plugin, for example `/oauth/callback` | Your page, on its own route |
| `POST /api/<relay>` and `GET /api/<relay>/{state}`: store and hand back, nothing else | Your backend, behind the gateway (not public paths) |
| Recording each `state` as issued to the person, and the exchange of the provider's code (`POST /api/oauth/states`, `POST /api/oauth/connect` below) | Your backend, behind the gateway, as the provider documents the exchange |

## The page that opens the popup

```ts
import { createPopupState } from '@epicstaff/plugin-sdk';

const json = { 'content-type': 'application/json' };

connectButton.addEventListener('click', () => {
    const session = login.session;
    if (!session) return;
    // <org id>.<random>: the provider's OAuth `state`.
    const state = createPopupState(session.org.id);
    const providerUrl = buildProviderAuthorizeUrl({ state, redirectUri: `${location.origin}/oauth/callback` });
    // First: a popup is allowed only right in the click handler.
    const result = login.openPopup(providerUrl, { state, relay: { statusPath: `/api/oauth-relay/${state}` } });
    // Then record the state as issued to this person.
    const issued = login.fetch('/api/oauth/states', { method: 'POST', headers: json, body: JSON.stringify({ state }) });
    Promise.all([result, issued])
        .then(([popup]) =>
            login.fetch('/api/oauth/connect', {
                method: 'POST',
                headers: json,
                body: JSON.stringify({ state, code: popup.params['code'] }),
            })
        )
        .then(showConnected, showError);
});
```

- Call `openPopup` **directly in the click handler**, before any `await`: browsers block a popup opened later
  (`popup_blocked`). It opens only `http:` and `https:` addresses (`invalid_popup_url` otherwise). Record the state
  with your backend right after; or have your backend issue the state before the click (when the page shows the
  button) and use that one.
- `createPopupState(orgId)` gives `<org id>.<43 random characters>`. Put it in the provider's `state` parameter.
- Exchange the provider's code only here, after `openPopup` resolved, on the page that issued the `state`
  ([why](#exchange-the-code-only-from-the-page-that-issued-the-state)).
- `openPopup` resolves with `{via, params, relayBody}`: `via` is `opener` or `relay`, `params` are the query and
  fragment parameters of the return page, and `relayBody` is your relay's whole answer. It rejects with
  `popup_timeout` after 10 minutes. Closing the popup is not detected: a browser reports a popup cut off by the
  provider as closed too.

## The return page

```ts
const plugin = await startPlugin();
const login = createPluginLogin(plugin);
if (location.pathname === '/oauth/callback') {
    const outcome = await login.completePopup({ relayPath: '/api/oauth-relay' });
    render(outcome.status === 'posted' || outcome.status === 'relayed' ? 'Done — you can close this window.' : '…');
} else {
    await login.start();
}
```

Call `completePopup` **instead of** `start()` on this page. It:

1. **With an opener:** posts `{"type":"es:popup-result","protocol":1,"state","params"}` to it, with your own origin as
   the target (never `*`), and closes the window. Outcome `posted`.
2. **Without one, and with `relayPath`:** stores the parameters in `sessionStorage`, removes them from the address, and
   signs the person in to the organization named by the `state` prefix: the window goes to EpicStaff and comes back
   (outcome `signing-in`; call `completePopup` again when the page loads). The provider's parameters are never sent to
   EpicStaff; only the path of the return page is kept to come back to. Then it posts `{"state", "params"}` to
   `relayPath` with the person's token and closes the window where the browser allows it. Outcome `relayed`.
3. Otherwise: `no-opener` (no opener and no relay), `invalid` (no valid `state`), `access-denied`, or `failed` with
   an `error` (`relay_failed` when your relay refused; the parameters are kept, so a reload tries again).

Show "Done — you can close this window" after `posted` or `relayed`: a window cut off from its opener may not be
allowed to close itself.

## The relay in your backend

Both endpoints are ordinary API paths: the gateway lets only a signed-in person through, and your backend reads who
it is from the [gateway context](../reference/gateway-context.md).

| Endpoint | Contract |
|---|---|
| `POST /api/<relay>` | Body `{"state": "<org id>.<random>", "params": {"name": "value", …}}`. Refuse it unless the `state` prefix equals the context's organization id. Store `{user id, org id, params}` under `state`, briefly (minutes). Answer `204`. **Only store**: never exchange the code, link an account or act on the parameters here |
| `GET /api/<relay>/{state}` | When `state` is stored **for the same user and organization** as the context: `200 {"status":"done","params":{…}}`, and delete it. Anything else, including another person's `state`: `200 {"status":"pending"}` |

The SDK asks the `GET` every 2 seconds for up to 10 minutes. Keep the store in your database; the Weather sample keeps
it in memory, which only works for a sample with one process.

**Checks that matter:** the `state` must belong to the person and organization asking; answer `pending`, not an error,
for a `state` that is not theirs, so a guessed `state` reveals nothing; delete the entry once read; never put the
provider's code in a URL or a log.

## Exchange the code only from the page that issued the state

Anyone can send a person to your return page with a code of their own:
`/oauth/callback?code=<theirs>&state=<the person's org id>.<anything>`. Without an opener, `completePopup` signs that
person in and posts the stranger's code to your relay, with the person's own token. If your backend exchanged that
code and connected the account there, the person's account in your plugin would be linked to the stranger's account
at the provider (a login CSRF). So:

- **The relay only stores.** `POST /api/<relay>` keeps the parameters for the `GET` to hand back, and nothing else.
- **Only the page that issued the `state` exchanges the code**, after `openPopup` resolved: that page is the only one
  that knows the `state`, and it gets the code from the opener message or from the relay.
- **The exchange endpoint checks the `state`**: it must be one your backend recorded as issued to this person, in
  this organization, recently, and not used yet. Mark it used before exchanging the code; refuse anything else.

A stranger's code then ends in the relay, unread, and expires there.

## Try it

The [Weather sample](../../../plugin-samples/weather/) has a demo provider (`GET /api/demo-provider`, a public path)
that sends back `code=demo-<16 hex>` with `state`, and with `coop=1` also `Cross-Origin-Opener-Policy: same-origin`.
Its `/connect` page has a button for each path; its `/oauth-demo/callback` page calls `completePopup`, and its backend
implements the relay at `/api/popup-relay`. The sample's relay only stores and hands back, as above. The demo has no
account to connect, so the page only shows the code it got back; a real plugin adds the state record and the
exchange.
