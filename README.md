![EpicStaff Logo](LOGO_ver2.png)

   <div align="center">  
      
# EpicStaff: AI Agent Orchestration for Operations Teams
 Source-Available Agent Orchestration Platform — Self-Hosted, Django-Backed
</div>

<a id="readme-top"></a>

<div align="center">  
   
[![GitHub Stars](https://img.shields.io/github/stars/EpicStaff/EpicStaff?style=social)](https://github.com/EpicStaff/EpicStaff/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/EpicStaff/EpicStaff?style=social)](https://github.com/EpicStaff/EpicStaff/network/members)
[![License](https://img.shields.io/github/license/EpicStaff/EpicStaff)](https://github.com/EpicStaff/EpicStaff/blob/main/LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/EpicStaff/EpicStaff)](https://github.com/EpicStaff/EpicStaff/commits/main)
[![Open Issues](https://img.shields.io/github/issues/EpicStaff/EpicStaff)](https://github.com/EpicStaff/EpicStaff/issues)

</div>

<p align="center">
<br />
  <a href="https://www.epicstaff.ai">Website</a> •
  <a href="https://github.com/EpicStaff/EpicStaff/wiki">Wiki</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#key-features">Key Features</a> •
  <a href="https://github.com/EpicStaff/EpicStaff/issues">Report Bug</a>
</div>

  <p align="center">
    <b>EpicStaff is a platform for building AI agent flows that operations teams own.</b>
    <br />
The deployment model is self-hosted and source-available. Engineers connect EpicStaff to your internal systems through MCP and Python — the same way they would connect any other in-house service. The visual editor runs over a Django backend, so every node can be inspected, every step edited, and every decision the agent makes reviewed.
     <div align="center">
   
Our core philosophy: **We hide the complexity, not the logic.**

**⭐ Star the repository if EpicStaff is useful in your work.**
</div>

---
## Keep your coding agent

Keep your coding agent. It writes tools, flows, and routing rules brilliantly — EpicStaff is the governed runtime they run in: session ledger, sandboxed execution, per-agent permissions, and a canvas your operations team can read.

---
 <p align="center">
    
## Visual Agent Orchestrator in Action

![Watch the EpicStaff Demo](https://github.com/user-attachments/assets/1b4659da-a79a-4da7-ab33-745702befd75)
</div>
    
---

## Why did we create EpicStaff?

Agent workflows have an ownership problem. Today, most agent flows live in code — written by engineers, readable only by engineers, and inaccessible to the operations teams that run the processes or the auditors who have to approve them. Operations teams cannot inspect or modify flows without engineering involvement. When something goes wrong mid-process, there is no audit trail. When the business logic changes, someone files a ticket and waits.

EpicStaff is built to close that gap: a platform where operations teams own the flows, engineers integrate the systems, and every decision an agent makes is reviewable and editable — without rebuilding from scratch.

* **Visual Logic, Python Core:** Design flows in a drag-and-drop AI workflow editor; inject custom Python logic directly into any node.
* **Cross-Flow Agent Context:** Built-in persistent agent memory (Redis/PostgreSQL) to retain context across multiple sessions.
* **Production-Ready Persistence:** Built-in state management for user and organization variables.
* **Django Multi-Agent Backend:** Powered by Django for robust, low-latency, and production-ready Pythonic agent orchestration.

---

## ⚡ Quick Start

Deploy self-hosted AI agents wherever you want to run them. EpicStaff runs in any environment you control — your laptop, your servers, your cloud.
Follow these two steps to get the application running.

### Step 1: Get the necessary tools
Before we start, make sure you have these two applications installed:
* **[Download & Install Git](https://git-scm.com/downloads)** (Required to download the app)
* **[Download & Install Docker Desktop](https://www.docker.com/products/docker-desktop/)** (Required to run the app)

### Step 2: Download and Setup
Choose your operating system below, open your **Terminal** (or PowerShell on Windows), and **paste the entire block of code**. This command will automatically download EpicStaff, generate its configuration file with development defaults, and start the system.

#### 🪟 Windows (PowerShell)
```
git clone https://github.com/EpicStaff/EpicStaff.git; cd EpicStaff; docker run --rm -it -v "${PWD}:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --root-user-action=ignore --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup --dev"; cd src; docker volume create sandbox_venvs; docker volume create crew_pgdata; docker volume create media_data; docker volume create opensearch_data; docker network create mcp-network; docker compose up --build
```
#### 🍎 macOS (Terminal)
```
git clone -b main https://github.com/EpicStaff/EpicStaff.git && cd EpicStaff && docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --user --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup --dev" && docker volume create sandbox_venvs && docker volume create crew_pgdata && docker volume create media_data && docker volume create opensearch_data && docker network create mcp-network && cd src && docker compose up --build
```
#### 🐧 Linux (Terminal)
```
git clone -b main https://github.com/EpicStaff/EpicStaff.git && cd EpicStaff && docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --user --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup --dev" && docker volume create sandbox_venvs && docker volume create crew_pgdata && docker volume create media_data && docker volume create opensearch_data && docker network create mcp-network && cd src && docker compose up --build
```

These blocks build every image locally from the cloned source (`docker compose up --build`). The signature and SBOM checks under [How to verify a release](#how-to-verify-a-release) apply only to images pulled from `ghcr.io/epicstaff`, never to images built on your machine. To run the signed, digest-pinned images of a release instead, see [Running a verified release](#running-a-verified-release).

The blocks generate `src/.env` with `python scripts/envtool.py --setup --dev`, run inside a
`python` container so only Docker is needed. It asks which optional features to turn on (chat,
the audit trail and plugins) and fills in everything else. These are **development defaults, for trying
EpicStaff on your own machine only**.

**Before running EpicStaff in production, replace this development configuration.** On the
server, from the cloned `EpicStaff` folder, run the same container with `--setup` and without
`--dev`:

```
# Windows (PowerShell)
docker run --rm -it -v "${PWD}:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --root-user-action=ignore --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup"
# macOS / Linux
docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/repo" -w /repo python:3.12.10-slim sh -c "pip install -q --user --disable-pip-version-check pyyaml==6.0.3 && python scripts/envtool.py --setup"
```

It asks for the public URL, how HTTPS is handled, which features to turn on and which release
tag to pull, and generates every password and key into `src/.env` (keep that file private). It can
also size the server and set the longest a code node may run. Run it again later to turn
features on or off, tune those limits, add settings a newer release introduced, or start over; it
keeps the existing credentials, because the databases were created with them.

Once running, open http://localhost to start building.

<details>
<summary>Alternative Setup Options</summary>

EpicStaff can be configured and launched using alternative setup methods:

- **[Partly Local Setup](https://github.com/EpicStaff/EpicStaff/blob/main/partly-local-setup.md)** — run specific services locally while other services remain in Docker. Useful for controlled local development and testing.  
- **[Podman Support](https://github.com/EpicStaff/EpicStaff/blob/main/podman-setup.md)** — provides instructions for deploying EpicStaff using **Podman** instead of Docker.

> These methods are optional and intended for users requiring advanced control over their environment.

**For more [details](https://github.com/EpicStaff/EpicStaff/wiki)**
</details>

---

## 🔄 Updating

An install from the Quick Start runs images it built from source. To move it to a newer
release, check out that release and run its published images instead. Pick the version from
the [Releases](https://github.com/EpicStaff/EpicStaff/releases) page:

```bash
cd EpicStaff
git fetch --tags
git checkout vX.Y.Z
```

In `src/.env`, set `IMAGE_TAG=vX.Y.Z` (the same release), and add any variable the new
`src/.env.example` marks as required that your `src/.env` does not have yet — compose names a
missing one and refuses to start. Then:

```bash
cd src
docker compose pull
docker compose up -d
```

`docker compose pull` fetches that release's `ghcr.io/epicstaff/*` images and `up -d`
recreates the services from them; `django_app` applies database migrations as it starts.

- **Always set `IMAGE_TAG` to an explicit release.** With the default `latest`, the pulled
  images and the ones you built share the name `ghcr.io/epicstaff/<service>:latest`, so a pull
  silently replaces your build with whatever `latest` points to at that moment.
- **Do not add `--build` from now on** — it rebuilds from source under the same name and
  replaces the images you pulled.
- **Back up your volumes first.** Migrations change the database on start, and there is no
  downgrade path.

If you run a [verified release](#running-a-verified-release), update by repeating those steps
with the new release's tag and files.

---

## How to verify a release

From v1.2.0 onward, every EpicStaff-built image (`ghcr.io/epicstaff/*`) shipped in a tagged release is pinned by digest in that release's `docker-compose.yaml` and signed keylessly via [Sigstore cosign](https://github.com/sigstore/cosign), using GitHub Actions OIDC as the identity provider — no private key material is involved. Each image also carries an attached SPDX Software Bill of Materials (SBOM), generated with [syft](https://github.com/anchore/syft) and attested with cosign. To verify an image, install `cosign` and run it against the exact `image:` reference from the release's `docker-compose.yaml`, checking that it was signed by this repo's `build-and-push.yml` workflow via the GitHub Actions OIDC issuer:

> **Note on the certificate identity:** `publish_release.yml` (which drives every release) can be started two ways — a `push` of a `vX.Y.Z` tag, or a manual `workflow_dispatch` run against an existing tag. The Fulcio certificate embedded in the signature encodes the git ref of the *top-level workflow run* at the moment it started, not the tag that was later checked out inside a job step. For a tag push that ref genuinely is `refs/tags/vX.Y.Z`. For a manual `workflow_dispatch` run it is whatever branch was selected in the "Run workflow" UI (`refs/heads/<branch>`, `main` by default — always dispatch releases from `main` unless you have a specific reason not to). The regexes below accept both forms so the verify command succeeds regardless of which trigger produced the release. The `heads/.+` alternative is not as open as it looks: `build-and-push.yml` only performs cosign signing when invoked with its `is_release` input set to `true`, and `publish_release.yml` is the sole caller that sets it — every other trigger, including ordinary branch/`main` pushes and ad-hoc manual runs of `build-and-push.yml` itself, produces no signature at all. So a `heads/<branch>` certificate identity can only ever come from a manual `workflow_dispatch` of `publish_release.yml`, never from an arbitrary test branch.

```bash
cosign verify \
  --certificate-identity-regexp "^https://github.com/EpicStaff/EpicStaff/\.github/workflows/build-and-push\.yml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/.+)$" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/epicstaff/django_app@sha256:<digest-from-compose-file>
```

To inspect the attached SBOM instead of (or in addition to) the signature, use `cosign verify-attestation` with the same identity flags and `--type spdxjson`:

```bash
cosign verify-attestation \
  --type spdxjson \
  --certificate-identity-regexp "^https://github.com/EpicStaff/EpicStaff/\.github/workflows/build-and-push\.yml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/.+)$" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/epicstaff/django_app@sha256:<digest-from-compose-file> \
  | jq -r '.payload | @base64d | fromjson | .predicate' > django_app.spdx.json
```

The release's `docker-compose.yaml` and `.env.example` are signed as well, because the compose file is what decides *which* digests you run: an altered copy could point at an older, genuinely signed EpicStaff image and every per-image check above would still pass. Each file ships with a Sigstore bundle (`<file>.sigstore.json`) produced by `cosign sign-blob` in `publish_release.yml`, so the certificate identity names that workflow rather than `build-and-push.yml`. Verify the files before using them:

```bash
cosign verify-blob \
  --bundle docker-compose.yaml.sigstore.json \
  --certificate-identity-regexp "^https://github.com/EpicStaff/EpicStaff/\.github/workflows/publish_release\.yml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/.+)$" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  docker-compose.yaml
```

Repeat with `.env.example` and `.env.example.sigstore.json`. A modified file, including one whose digests were swapped for another release's, fails this check.

### Running a verified release

The release's `docker-compose.yaml` is not a standalone install: it still mounts `nginx/templates` and `nginx/certs` from the checkout next to it. Use it as an overlay on a clone of the same tag, so `docker compose up` pulls the digest-pinned images you just verified instead of building from source:

```bash
git clone -b vX.Y.Z https://github.com/EpicStaff/EpicStaff.git && cd EpicStaff
# Download docker-compose.yaml and docker-compose.yaml.sigstore.json from the
# vX.Y.Z release page into a separate folder, verify them as shown above, then:
cp /path/to/downloaded/docker-compose.yaml src/docker-compose.yaml
```

Prepare a production `src/.env` with `envtool.py --setup` as described under the Quick Start, create the volumes and network as in the Quick Start block for your OS, and finish with `docker compose up` instead of `docker compose up --build`. Nothing is built: each `ghcr.io/epicstaff/*` service is pulled by the digest pinned in the file, and the image checks above apply to exactly what runs.

---

## Key Features 

<details>
<summary>Key features For AI Engineers</summary>

EpicStaff is built for engineers shipping multi-agent systems to production. A node-based visual editor sits over a Django backend; any node can hold custom Python, RAG runs against a built-in vector store, and integration with internal systems happens via MCP or directly in Python. Self-hosted, source-available — full control over the runtime.

| Feature | Technical Description |
|---|---|
| Node UI | Construct complex workflows using a node-based architecture. Design execution graphs with various specialized nodes to define exact logic paths. |
| LLM & Embedder Providers | Native support for switching between major providers like OpenAI and Anthropic, or integrate your own custom local LLMs and embedding models. |
| Retrieval-Augmented Generation (RAG) | Upload documents, create knowledge collections and customize index parameters directly in the UI. Index data using strategies like Naive Vector Search or GraphRAG to enhance agent context. |
| Custom Tools | Write custom Python functions that agents can invoke dynamically. Build your own integrations, and the orchestration engine will automatically evaluate and use them during execution. |
| Code Execution | Inject and run Python code within nodes. Read, modify, and manipulate flow variables dynamically to handle custom logic during workflow traversal. |
| Flow Messages | Debug flow execution seamlessly. Read detailed, structured state messages and execution logs for each specific node in real-time. |
| Webhooks | Trigger flow executions programmatically. Initiate workflows via HTTP POST payloads from any external system, application, or custom source. |
| Persistent Agent Memory | Dual-Layer Memory: Short-term window context combined with long-term stateful memory across multiple sessions, stored in PostgreSQL (with pgvector) and Redis. |
</details>

---

<details>
<summary>Key Features For Business</summary>

EpicStaff is designed for operations teams that need to build, own, and audit AI agent workflows — running on their own infrastructure, approved by their own auditors. The platform bridges the gap between engineering (who build integrations) and operations (who run the process): engineers integrate via MCP and Python; operations teams configure, edit, and review in the visual workflow editor.

| Feature | Strategic Business Value |
|---|---|
| Visual Workflow Builder | A drag-and-drop interface, automate any process without any deep tech knowledge. You can build, validate, and visually debug multi-step workflows using our pre-built node library. |
| Multi-Agent Collaboration| Build a digital crew. Let multiple AI agents work together to automate entire departments. |
| Enterprise Security | Secure your organization with access controls. Create custom roles and assign specific permissions to safely manage your organisation's workflows and data. |
| Custom Python Tools | Build exactly what you need. Write custom logic in Python to easily connect with any external API or service, giving your business unlimited automation capabilities. | 
| Web Scraping & Image Generation | Scales content creation and research by automatically gathering web data and generating visual assets without requiring additional operational resources. |
| Webhook Triggers | Set up the agent workflow to respond to external events, like new emails, changes in CRM, or webhooks. It'll automatically start a chat with the customer, update the database, generate a report. |
| Voice Agent Capabilities | Control workflows with your voice. Speak naturally to your agents in multiple languages for completely hands-free automation. |
|Human Input Control| Maintains human oversight over sensitive operations by pausing workflows for manual review and validation before an agent executes a final decision.

</details>

---

## Contributing

EpicStaff accepts contributions on GitHub. Pull requests, issues, and new tool contributions are welcome.

* **⭐ Star the repository** if EpicStaff solves a problem you recognise.
* **🤝 Contribute** — see [CONTRIBUTING.md](CONTRIBUTING.md) to add a feature, fix a bug, or build a new tool.

## 🙏 Special Thanks

EpicStaff builds on work from the broader open-source ecosystem. Particular thanks to **[Foblex](https://github.com/Foblex)**.

* The **[f-flow library](https://github.com/Foblex/f-flow)** is the core interactive engine for the EpicStaff visual editor.
* Foblex features EpicStaff in their articles and educational materials at **[flow.foblex.com](https://flow.foblex.com/)**.

