/**
 * Personal environment override for local development.
 *
 * Why: so you don't have to edit the git-tracked environment.ts every time you
 * need to point the frontend at a different backend. environment.local.ts is
 * listed in .gitignore, so it never shows up as a pending change or lands in a commit.
 *
 * How to enable:
 *   1. Copy this file next to it as environment.local.ts
 *        cp src/environments/environment.local.example.ts src/environments/environment.local.ts
 *   2. Run the frontend with:
 *        npm run start:local
 *
 * A plain `npm start` keeps using the repository's environment.ts.
 * The swap is wired up through the `local` configuration in angular.json (fileReplacements).
 *
 * WARNING: Do NOT set apiUrl / realtimeApiUrl to absolute cross-site URLs (a remote stand
 * or 127.0.0.1). Doing so causes the browser to drop the SameSite=Lax refresh cookie and
 * the session silently dies after the first token refresh. Keep the URLs relative and
 * point the proxy at the backend instead (see PROXY_TARGET below).
 */
export const environment = {
    production: false,

    // Keep these relative. The dev-server proxy (proxy.conf.js) forwards them to
    // whichever backend PROXY_TARGET points at — defaulting to http://localhost.
    apiUrl: '/api/',
    realtimeApiUrl: '/realtime/',

    // To target a different backend, set PROXY_TARGET before starting the dev server:
    //   PROXY_TARGET=https://some-stand.example.com npm run start:local
    // Leave PROXY_TARGET unset to use the local docker backend at http://localhost.

    isEpicChatEnabled: true,
};
