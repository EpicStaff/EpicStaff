![EpicStaff Logo](LOGO_ver2.png)

   <div align="center">  
      
# EpicStaff: Enterprise Workflow Automation & AI Agent Management Platform
 Open Source Agent Orchestration Framework for Django & Python
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
    <b>Production-Grade Agentic UI for Multi-Agent Orchestration</b>
    <br />
EpicStaff is an Enterprise-ready Agentic UI platform that simplifies multi-agent orchestration by hiding complexity behind a visual workflow builder while maintaining full code control with a Django backend.
     <div align="center">
   
Our core philosophy: **We hide the complexity, not the logic.**

**⭐ Star us on GitHub to support the Agentic UI movement!**
</div>

---
 <p align="center">
    
## Visual Agent Orchestrator in Action

![Watch the EpicStaff Demo](https://github.com/EpicStaff/EpicStaff-resources/blob/main/how_to_create_flow.gif?raw=true)
</div>
    
---

## Why did we create EpicStaff?

Most tools force a trade-off: simplicity (No-Code) vs. flexibility (Code-First). **EpicStaff** eliminates this barrier by providing a **Visual + Code** hybrid environment.

It is a high-performance orchestration platform designed to allow developers to build, deploy, and scale multi-agent systems without losing control over the underlying logic.

* **Visual Logic, Python Core:** Design flows in a drag-and-drop AI workflow editor; inject custom Python logic directly into any node.
* **Cross-Flow Agent Context:** Built-in persistent agent memory (Redis/PostgreSQL) to retain context across multiple sessions.
* **Production-Ready Persistence:** Built-in state management for user and organization variables.
* **Django Multi-Agent Backend:** Powered by Django for robust, low-latency, and production-ready Pythonic agent orchestration.

---

## ⚡ Quick Start

Deploy self-hosted AI agents in 30 seconds. EpicStaff is designed to run securely on your own infrastructure.
Follow these two simple steps to get the application running on your computer.

### Step 1: Get the necessary tools
Before we start, make sure you have these two applications installed:
* **[Download & Install Git](https://git-scm.com/downloads)** (Required to download the app)
* **[Download & Install Docker Desktop](https://www.docker.com/products/docker-desktop/)** (Required to run the app)

### Step 2: Download and Setup
Choose your operating system below, open your **Terminal** (or PowerShell on Windows), and **paste the entire block of code**. This command will automatically download EpicStaff, configure the database, and start the system.

#### 🪟 Windows (PowerShell)
```
git clone [https://github.com/EpicStaff/EpicStaff.git](https://github.com/EpicStaff/EpicStaff.git); cd EpicStaff/src; $savefiles = "$HOME/savefiles"; $file = ".env"; (Get-Content $file) -replace "CREW_SAVEFILES_PATH=/c/savefiles", "CREW_SAVEFILES_PATH=$savefiles" | Set-Content $file; docker volume create sandbox_venvs; docker volume create sandbox_executions; docker volume create crew_pgdata; docker volume create crew_config; docker volume create media_data; docker network create mcp-network; docker-compose up --build
```
#### 🍎 macOS (Terminal)
```
git clone -b main [https://github.com/EpicStaff/EpicStaff.git](https://github.com/EpicStaff/EpicStaff.git) && cd EpicStaff && savefiles="$HOME/savefiles" && sed -i '' "s|CREW_SAVEFILES_PATH=/c/savefiles|CREW_SAVEFILES_PATH=$savefiles|" src/.env && docker volume create sandbox_venvs && docker volume create sandbox_executions && docker volume create crew_pgdata && docker volume create crew_config && docker volume create media_data && docker network create mcp-network && cd src && docker-compose up --build
```
#### 🐧 Linux (Terminal)
```
git clone -b main [https://github.com/EpicStaff/EpicStaff.git](https://github.com/EpicStaff/EpicStaff.git) && cd EpicStaff && savefiles="$HOME/savefiles" && sed -i "s|CREW_SAVEFILES_PATH=/c/savefiles|CREW_SAVEFILES_PATH=$savefiles|" src/.env && docker volume create sandbox_venvs && docker volume create sandbox_executions && docker volume create crew_pgdata && docker volume create crew_config && docker volume create media_data && docker network create mcp-network && cd src && docker-compose up --build
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

We built a foundation for robust ai agent orchestration and Open Source Agent Orchestration. You can design ai agent orchestration for complex workflows and deploy autonomous AI agents with complete control over the execution logic. The architecture natively supports creating a dependable rag pipeline and managing advanced RAG workflows without external vector database dependencies. For developers exploring the code, we ensure stable execution to prevent the notorious ralph wiggum loop, and you might even spot a ralph wiggum github reference in our test repositories.

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

As an ai agent management platform, EpicStaff is engineered to deliver enterprise workflow automation and scalable business process automation. It functions as an Autonomous Agent Builder that acts as a drag and drop automation tool for cross-functional teams. By utilizing sophisticated ai workflow management and built-in ai agent assist, organizations can drastically improve their AI CX (ai customer experience). Being a versatile low code platform, it bridges the gap between technical operations and business strategy.

| Feature | Strategic Business Value |
|---|---|
| Visual Workflow Builder | A low-code, drag-and-drop interface, automate any process without any deep tech knowledge. You can build, validate, and visually debug multi-step workflows using our pre-built node library. |
| Multi-Agent Collaboration| Build a digital crew. Let multiple AI agents work together to automate entire departments, decreasing operational costs and saving time. |
| Enterprise Security | Secure your organization with access controls. Create custom roles and assign specific permissions to safely manage your organisation's workflows and data. |
| Custom Python Tools | Build exactly what you need. Write custom logic in Python to easily connect with any external API or service, giving your business unlimited automation capabilities. | 
| Web Scraping & Image Generation | Scales content creation and research by automatically gathering web data and generating visual assets without requiring additional operational resources. |
| Webhook Triggers | Set up the agent workflow to respond to external events, like new emails, changes in CRM, or webhooks. It'll automatically start a chat with the customer, update the database, generate a report. |
| Voice Agent Capabilities | Control workflows with your voice. Speak naturally to your agents in multiple languages for completely hands-free automation. |
|Human Input Control| Maintains human oversight over sensitive operations by pausing workflows for manual review and validation before an agent executes a final decision.

</details>

---

## Join Our Community & Shape the Future of EpicStaff

EpicStaff is an open-source project driven by its community. Whether you want to build custom Python tools, improve the Django backend, or design new Agentic UI components, your contributions matter!

* **⭐ Star the Repository:** Support the Agentic UI movement.
* **💬 Connect on Reddit:** For real-time chat with the community and the core team, join our [Reddit Community](https://www.reddit.com/r/EpicStaff_AI/). 
* **🤝 Contribute:** Found a bug or want to add a new tool? Check out our [CONTRIBUTING.md](CONTRIBUTING.md) to get started. We welcome all contributors!

**Let's build the future of intelligent, collaborative systems together!**

## 🙏 Special Thanks

Our visual-first agentic system leverages the innovative work of the open-source community. A special thank you to **[Foblex](https://github.com/Foblex)**

* We proudly use the **[f-flow library](https://github.com/Foblex/f-flow)** as the core interactive engine for our Agentic UI.
* Foblex helps us spread the word by featuring EpicStaff in his articles and educational materials. You can check out his work at **[flow.foblex.com](https://flow.foblex.com/)**.

We believe in the power of collaboration and are grateful for such a great partnership.


