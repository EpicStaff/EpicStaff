# Plugins — documentation index

Prototype on branch `proto/plugins-06-10-26` (never merged to `main`). These docs describe the concept **as built at
`bfeea626f` (2026-10-07)** — simple plugin pages (bridge v1) and full plugin apps (bridge v2) — and are the baseline
before the concept is reworked. New here? Read the PRD, then the architecture.

## Concept

- [Plugins — product requirements](plugins-prd.md) — prd · draft — the idea (mini-app on EpicStaff: backend + page or full app + access list), users, journey, confirmed requirements incl. plugin apps, scope, open questions
- [Plugins — architecture](plugins-architecture.md) — architecture · draft — relation to EpicStaff (reused vs new), C4 context / container / component diagrams of the host and backend, key decisions, known gaps
- [Plugins — rules](plugins-rules.md) — rules · draft — security, install, lifecycle, dev mode, RBAC and upgrade invariants every change must keep
- [Plugins glossary](plugins-glossary.md) — glossary · draft — plugin, page vs app, access list, alias, bridge, app path, theme tokens, dev mode, SDK, …

## Protocols and formats

- [Plugin package format](plugin-package-format.md) — protocol · draft — the plugin file: layout, plugin.json, key-value tables in resources.json, rejection rules, sandbox rules for frontends, install sequence
- [Plugin bridge v1](plugin-bridge-v1.md) — protocol · draft — frontend ↔ host: handshake, envelope, flow methods, access policy, limits, versioning, round-trip sequence
- [Plugin bridge v2](plugin-bridge-v2.md) — protocol · draft — what plugin apps add: `kv.list` / `kv.get`, deep links (`nav.*`), theme tokens, dev re-handshake, limits
- [Plugins API contract](api-contract.md) — protocol · stable — every `/api/plugins` endpoint (incl. dev-ui) with request/response JSON, errors, permissions, file serving headers

## Building plugins

- [Plugin author tooling — SDK, CLI, dev mode](plugin-author-tooling.md) — architecture · draft — the plugin side: SDK components (C4), author loop, dev mode, framework build settings, the Chat Admin sample
- [Plugins code map](code-map.md) — code-map · draft — every file of the feature by layer, contracts, conventions, gotchas (prototype branch only)

## History (how plugin apps were decided and built)

- [Plugin apps — alignment summary](alignment-plugin-apps-2026-10-07.md) — alignment · confirmed — the confirmed interview for plugin apps; secrets in the app left open
- [Plugin apps — implementation plan](plugin-apps-plan.md) — plan · done — frozen contracts and workstreams the build followed
- [Plugin apps — build status and morning test guide](plugin-apps-status.md) — status · draft — what was built and verified overnight, test steps, decisions taken, open items
