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

![Watch the EpicStaff Demo](https://github.com/EpicStaff/EpicStaff-resources/blob/main/how_to_create_flow.gif?raw=true)
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
Choose your operating system below, open your **Terminal** (or PowerShell on Windows), and **paste the entire block of code**. This command will automatically download EpicStaff, configure the database, and start the system.

#### 🪟 Windows (PowerShell)
```
git clone https://github.com/EpicStaff/EpicStaff.git; cd EpicStaff/src; $savefiles = "$HOME/savefiles"; $file = ".env"; (Get-Content $file) -replace "CREW_SAVEFILES_PATH=/c/savefiles", "CREW_SAVEFILES_PATH=$savefiles" | Set-Content $file; docker volume create sandbox_venvs; docker volume create crew_pgdata; docker volume create graph_data; docker volume create crew_config; docker volume create media_data; docker network create mcp-network; docker-compose up --build
```
#### 🍎 macOS (Terminal)
```
git clone -b main https://github.com/EpicStaff/EpicStaff.git && cd EpicStaff && savefiles="$HOME/savefiles" && sed -i '' "s|CREW_SAVEFILES_PATH=/c/savefiles|CREW_SAVEFILES_PATH=$savefiles|" src/.env && docker volume create sandbox_venvs && docker volume create crew_pgdata && docker volume create graph_data && docker volume create crew_config && docker volume create media_data && docker network create mcp-network && cd src && docker-compose up --build
```
#### 🐧 Linux (Terminal)
```
git clone -b main https://github.com/EpicStaff/EpicStaff.git && cd EpicStaff && savefiles="$HOME/savefiles" && sed -i "s|CREW_SAVEFILES_PATH=/c/savefiles|CREW_SAVEFILES_PATH=$savefiles|" src/.env && docker volume create sandbox_venvs && docker volume create crew_pgdata && docker volume create graph_data && docker volume create crew_config && docker volume create media_data && docker network create mcp-network && cd src && docker-compose up --build
```

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

