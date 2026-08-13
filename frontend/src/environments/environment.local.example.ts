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
 *   2. Set the URLs you need (see the examples below).
 *   3. Run the frontend with:
 *        npm run start:local
 *
 * A plain `npm start` keeps using the repository's environment.ts.
 * The swap is wired up through the `local` configuration in angular.json (fileReplacements).
 */
export const environment = {
    production: false,

    // Remote stand — no need to run the backend locally:
    apiUrl: 'https://some-stand.somedev.com/api/',
    realtimeApiUrl: 'https://some-stand.somedev.com/',

    // Local backend behind docker/nginx:
    // apiUrl: 'http://127.0.0.1/api/',
    // realtimeApiUrl: 'http://127.0.0.1/realtime/',

    // Local backend, services exposed directly on their ports:
    // apiUrl: 'http://127.0.0.1:8000/api/',
    // realtimeApiUrl: 'http://127.0.0.1:8050/',

    isEpicChatEnabled: true,
};
