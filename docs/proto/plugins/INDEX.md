# Plugins — documentation index

Prototype on branch `proto/plugins-06-10-26` (never merged to `main`). New here? Read the PRD, then the architecture.

- [Plugins — product requirements](plugins-prd.md) — prd · draft — the idea (mini-app on EpicStaff), users, confirmed requirements, scope, open questions
- [Plugins — rules](plugins-rules.md) — rules · draft — security, install, lifecycle, RBAC and upgrade invariants every change must keep
- [Plugins — architecture](plugins-architecture.md) — architecture · draft — relation to EpicStaff (reused vs new), C4 context/container/component diagrams, key decisions
- [Plugin package format](plugin-package-format.md) — protocol · draft — the plugin file: layout, plugin.json, rejection rules, sandbox rules for pages, install sequence
- [Plugin bridge v1](plugin-bridge-v1.md) — protocol · draft — page ↔ host: handshake, envelope, methods, access policy, limits, versioning, round-trip sequence
- [Plugins API contract](api-contract.md) — protocol · stable — every `/api/plugins` endpoint with request/response JSON, errors and permissions
- [Plugins glossary](plugins-glossary.md) — glossary · draft — plugin, access list, alias, secret slot, bridge, host, page token, suspend, …
- [Plugin apps — build status and morning test guide](plugin-apps-status.md) — status · draft — what was built, what was verified, how to test, env changes, open items, proposed commits
- [Plugin apps — implementation plan](plugin-apps-plan.md) — plan · in-progress — frozen contracts (manifest, KV export entity, REST, asset serving, bridge v2, conversation record), workstreams, verification, risks
- [Plugin apps — alignment summary](alignment-plugin-apps-2026-10-07.md) — alignment · confirmed — next step: full-framework plugin apps reading the plugin's own KV table, SDK + dev mode; secrets open
