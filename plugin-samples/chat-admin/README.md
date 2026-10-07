# Chat Admin — sample plugin with an app

A support chat bot packaged as an EpicStaff plugin **with its own frontend app**. The plugin ships a chat flow, the
agent and LLM config it uses, and a key-value table the flow stores conversations in. The app opens inside EpicStaff
(one icon in the left bar) and has three screens:

- **Chat** (`/chat`, `/chat/<id>`) — ask the assistant; continue any stored conversation.
- **Conversations** (`/conversations`) — every conversation, with search by id, sorting and paging; each opens its full
  transcript (`/conversations/<key>`) with a **Continue in chat** link.
- **About** — the plugin's identity, its access list and the live theme mode.

It is the reference for building plugin apps: Angular 22 (standalone, zoneless, hash routing, lazy routes), bundled
web fonts, EpicStaff's theme tokens, address-bar sync, and the SDK's mock host for working without EpicStaff. Author
guide and API: [`plugin-sdk/README.md`](../../plugin-sdk/README.md).

```
plugin-samples/chat-admin/
├── plugin/            plugin.json + resources.json (the flow export) — the zip root
└── app/               the Angular app; its build becomes ui/ in the zip
```

## How it works

| | |
|---|---|
| Access list | `chat` — the flow: `run`, `sessions.read`, `sessions.stop`; `conversations` — the key-value table: `read` |
| Installed table | `chat_admin__conversations` (plugin tables carry the plugin prefix; install always creates a new one) |
| One turn | the app calls `flows.runAndWait('chat', {conversation_id, question})`; the flow loads the record from the table, answers, appends the turn and saves the record; its End node returns `{answer, conversation_id}` |
| App's role | read-only: it never writes the table, and it sends only the id and the question (a whole transcript would soon exceed the bridge's 64 KB request limit) |
| Conversation id | `c_` + 24 random hex characters, made by the app; it is also the row's key |

The record the flow writes (one row per conversation, ≤ 200 000 bytes — the oldest question/answer pairs are dropped
first):

```json
{"title": "first question, ≤80 chars", "turns": 2,
 "messages": [{"role": "user", "content": "…", "at": "2026-10-07T10:00:00Z"},
              {"role": "assistant", "content": "…", "at": "2026-10-07T10:00:04Z"}],
 "started_at": "…", "updated_at": "…", "conversation_id": "c_0123456789abcdef01234567"}
```

The list shows title and turns from `kv.list`'s 200-character `value_preview` (cut mid-record for long conversations,
so the app reads the leading `title` and `turns` — Postgres prints `jsonb` keys shortest first); a row it cannot read
shows its key.

## Build

Node **≥ 24.15** (or ≥ 22.22.3) — Angular CLI 22 refuses older versions.

```
cd plugin-samples/chat-admin/app
npm install
npm run build          # compiles the SDK (prebuild), then ng build → dist/chat-admin/browser/
```

On an older local Node, run the same builder past the CLI's version check (local workaround only; Docker and CI use a
newer Node):

```
npm run build:sdk && node node_modules/@angular/cli/bin/bootstrap.js build
```

The production build is set up for the plugin sandbox: no `<base>`, no inline scripts, `inlineCritical: false`,
`fonts: false`, hashed file names, no source maps; the storage stand-in is the first import of `main.ts` and also a
`polyfills` entry.

## Validate and pack

```
npm run validate       # plugin/ + dist/chat-admin/browser as ui/
npm run pack           # → app/dist/chat-admin-plugin.zip
```

or from the repository root, with any output path:

```
node plugin-sdk/bin/epicstaff-plugin.mjs pack plugin-samples/chat-admin/plugin \
  --ui plugin-samples/chat-admin/app/dist/chat-admin/browser --out ../chat-admin-plugin.zip
```

`plugin/resources.json` is generated, not hand-written:
`make django-manage CMD="plugin_export_resources --sample chat-admin --output ../../plugin-samples/chat-admin/plugin/resources.json"`.

## Install

1. In EpicStaff open **Plugins** → add a plugin → drop `chat-admin-plugin.zip`.
2. The review lists the flow, its agent and LLM config, the key-value table `chat_admin__conversations`, the access
   ("Run flow …", "Read key-value table …") and the Python-code warning. Enter an OpenAI API key for the
   `OPENAI_API_KEY` slot and install. You need permission to create every resource it installs, key-value tables
   included.
3. When it is **Ready**, the Chat Admin icon appears in the left bar.

The flow needs the sandbox service (its Python nodes) and a working OpenAI key.

## Run standalone (no EpicStaff)

```
npm start              # http://localhost:4300/
```

Outside a frame the SDK connects to a mock host with sample conversations (a lazy chunk; the production app never
loads it). Asking a question gets a canned answer after a short delay, and the conversation is saved to the mock
table exactly as the real flow saves it. A **Sample data** badge marks this mode.

## Dev mode (live app inside EpicStaff)

1. Run EpicStaff locally with `PLUGINS_DEV_MODE=true` and install the plugin from its zip (above).
2. `npm start` in `app/` (port 4300; every response carries `Access-Control-Allow-Origin: *`, which the sandboxed
   frame needs for module scripts and fonts).
3. As an admin with `plugins: update`: **Plugins** → Chat Admin → **Dev mode** → `http://localhost:4300/`.
4. Open Chat Admin from the left bar: a **DEV** banner shows the URL, the app runs from your dev server with real data,
   and every reload re-handshakes on its own. Only you see the dev app; clear the URL to return to the installed one.

## Notes for your own app

- Inside the sandbox a `<form>`'s `submit` event never fires (no `allow-forms`), so the chat composer uses a button
  `click` and an Enter `keydown` handler, not `(ngSubmit)`.
- The chat's open conversation lives in a root store (`ChatStore`), so switching tabs and the `/chat` → `/chat/<id>`
  step after the first question keep it.
- Search, sorting and paging live in the query string; typing replaces the history entry, sorting and paging push one,
  so EpicStaff's Back undoes them.
