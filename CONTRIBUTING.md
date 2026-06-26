# Contributing to EpicStaff

First off, thank you for considering contributing to EpicStaff! We're thrilled you're here. This project is driven by its community, and every contribution, no matter how small, helps us build a better platform.

This document provides a set of guidelines for contributing to EpicStaff. These are mostly guidelines, not strict rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Contributor License Agreement (CLA)

By submitting a pull request, you agree to our [Contributor License Agreement](CLA.md). For first-time contributors, the signing process is automated via a CLA bot.

## Code of Conduct

This project and everyone participating in it is governed by the [EpicStaff Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to **contact@epicstaff.com**.

## How Can I Contribute?

There are many ways to contribute, and not all of them involve writing code.

* **Reporting Bugs:** If you find a bug, please use our issue template to provide as much detail as possible.
* **Improving Documentation:** If you notice something is unclear, you can submit a pull request with your improvements.

## Using Our Templates: Issues and Pull Requests

To ensure consistency and clarity, we use templates for bug reports and pull requests. When you go to create a new issue or PR on GitHub, you will be prompted to fill out a form based on these templates.

### Reporting a Bug (Issue Template)

When you report a bug, our template will ask for the following information to help us understand and reproduce the problem:

* **About:** A clear and concise description of the issue.
* **Steps to Reproduce (STR):** Step-by-step instructions on how to reproduce the bug.
* **Expected Result:** What you expected to happen.
* **Actual Result:** What actually happened after following the steps.
* **Attachments:** Please include any relevant logs, videos, or screenshots.

### Submitting a Change (Pull Request Template)

To help us review your contribution efficiently, our pull request template will ask you to provide:

* **Type of change:** (e.g., bug fix, new feature, docs update).
* **Related Issue:** The issue number that your PR addresses (e.g., `Affects #123`).
* **Description:** A summary of the changes you have made.
* **Checklist:** You will be asked to confirm that you have completed several steps, such as:
    * [ ] Performed a self-review of your code.
    * [ ] Commented your code, particularly in hard-to-understand areas.
    * [ ] Added tests that prove your fix is effective or that your feature works.
    * [ ] Made corresponding changes to the documentation.
    * [ ] Ensured your changes generate no new warnings.

### Local Development Setup

These steps start the dev stack with Docker Compose directly. If you prefer `make` shortcuts, they are documented separately in **[docs/makefile_commands.md](docs/makefile_commands.md)**.

**Prerequisites:** Docker Desktop (running) and Git. Python 3 is optional — only needed for the env-file generator in step 4.

1.  **Fork the repository:** Click the "Fork" button at the top right of this page.
2.  **Clone your fork:**
    ```bash
    git clone https://github.com/YOUR_USERNAME/EpicStaff.git
    cd EpicStaff
    ```
3.  **Create a new branch:**
    ```bash
    git checkout -b your-feature-branch-name
    ```
4.  **Create the dev environment file `src/.dev.env`.** It is gitignored, so it does not exist on a fresh clone — pick one option:

    - **With Python** (recommended) — generate it from `src/env.yaml`, the single source of truth:
      ```bash
      python scripts/generate_env.py --env dev
      ```
      Re-run this whenever `src/env.yaml` changes. Do not hand-edit the generated file.

    - **Without Python** — copy the example template:
      ```bash
      cp src/.env.example src/.dev.env
      ```
      `.env.example` is the **production** template, so edit `src/.dev.env` afterwards: fill in every value marked `CHANGE ME`, and set the local-dev flags `DEBUG=True` and `LOAD_DEBUG_ENV=True`.

5.  **Create the external Docker volumes and network** (one time per machine — Compose will not create these automatically):
    ```bash
    docker volume create sandbox_venvs
    docker volume create crew_pgdata
    docker volume create media_data
    docker volume create graph_data
    docker network create mcp-network
    ```
6.  **Start the dev stack** (live-reload, mapped ports). Run from the `src/` directory:
    ```bash
    cd src
    docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file=.dev.env up -d
    ```
7.  Open **http://localhost** in your browser. The Angular live-reload dev server is also directly accessible at **http://localhost:4200**.
8.  **Make your changes and run tests.**
9.  **Commit and push your changes**, then **submit a Pull Request.**

To tail logs, run (from `src/`) `docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file=.dev.env logs -f`. To stop the stack, replace `logs -f` with `down`.

### Pull Request Process

1.  Ensure your PR has a clear title and description, as guided by our template.
2.  The core team will review your PR. We may suggest some changes.
3.  Once approved and all checks have passed, your PR will be merged. Thank you!

## Any Questions?

If you get stuck, don't hesitate to ask in our [Reddit Community](https://www.reddit.com/r/EpicStaff_AI/).

We're excited to see what you build with us!

