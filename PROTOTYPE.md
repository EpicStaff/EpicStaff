# Prototype: Plugins

**Branch:** `proto/plugins-06-10-26`
**Created:** 06-10-26
**Branched from:** `developer` @ `cdb8bcf30`
**Status:** in progress

## Idea

An admin drops a plugin file (zip with `plugin.json`) into Settings → Plugins and the org gets a working bundle —
flows, agent, tools, LLM/embedding configs, files, knowledge, secret slots — plus the plugin's own UI page in the
navigation, running in a sandboxed iframe that talks to EpicStaff only through a versioned postMessage bridge, as the
logged-in user capped by the plugin's access list. Worked example: a chat-bot plugin. Suspend and delete included.

## What works

- _(nothing yet)_

## What's unfinished / known-broken

- _(nothing yet)_

## Where the interesting code is

- _(nothing yet)_

## To pick this up again

- _(nothing yet)_

---

Prototype-grade code: intentionally unrefactored, unreviewed, and not production-ready.
Do not merge this branch into `main`.
