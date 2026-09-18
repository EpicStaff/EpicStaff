# CLA Signature Storage — How It Works

EpicStaff stores Contributor License Agreement (CLA) signatures in a private
**Google Shared Drive** instead of in the repository. This document explains how
the CLA flow operates and lists the configuration it depends on.

---

## Overview

- Signatures live in a Google **Shared Drive**, accessed by CI through a Google
  **service account**.
- Signatures are keyed by **CLA version** (one folder per version), with **one
  JSON file per signer**.
- On every PR, **all commit authors** must have signed the **current** CLA
  version before the build is allowed to run.
- The whole system is gated by the `CLA_ENFORCED` repo variable — set it to
  anything other than `true` and the CLA gate is skipped entirely.

> The CLA data is private, so it cannot be reached with a plain Google API key
> (those only serve public data). CI authenticates as a service account, which
> has no personal storage quota — that is why the files must live in a Shared
> Drive owned by the organization, with the service account added as a member.

---

## Storage layout

The CLA version is parsed from the `CLA.md` H1 heading (`... - VERSION 1.0.0`).
Each version gets its own folder; older versions are retained as history. Signer
files are named `{github_login}_{github_id}.json`:

```
<CLA_GDRIVE_ROOT_ID>/           # a folder in the Shared Drive
├── v1.0.0/                     # current version — checked on every PR
│   ├── octocat_583231.json
│   └── alice_12345.json
└── v0.9.0/                     # previous version — kept, no longer checked
    └── octocat_583231.json
```

Each signature file:

```json
{
  "github_login": "octocat",
  "github_id": 583231,
  "cla_version": "1.0.0",
  "cla_sha256": "<64-hex SHA-256 of CLA.md>",
  "comment_text": "I have read the CLA Document and I hereby sign the CLA",
  "comment_url": "https://github.com/OWNER/REPO/pull/12#issuecomment-123",
  "pull_request_no": 12,
  "signed_at": "2026-07-20T10:12:00Z"
}
```

### What `cla_sha256` is and why it's stored

A **SHA-256 hash** is a fixed-length fingerprint of the `CLA.md` bytes. Changing a
single character produces a completely different digest. Storing it with each
signature records *exactly which document text the person agreed to*: it lets you
prove the CLA was not altered after signing, and it detects if `CLA.md` was edited
without bumping its version. The hash is computed with line endings normalized to
`\n`, so Windows and Linux checkouts of the same content hash identically. If a
signature's stored hash no longer matches the current `CLA.md`, that signature is
treated as **stale** (not valid for the current content).

---

## The signing and enforcement flow

Two workflows cooperate. They run on different, asynchronous events.

### `cla.yml` — collect signatures + decide the verdict

Runs on `pull_request_target` and `issue_comment`. It has access to the Drive
credentials. `pull_request_target` runs in the base-repo context and does not
execute PR code, so this is safe even for pull requests from forks (which is where
external contributors sign). On each run it:

1. Resolves **all commit authors** of the PR via the GitHub API.
2. Checks the current version folder in Drive for each author's signature (and
   that the stored hash still matches).
3. Posts or updates a single PR comment listing anyone who still needs to sign.
4. Sets a commit status named **`CLA`** (`success` / `failure`) on the PR head
   commit. This status is the actual verdict.

A contributor **signs** by posting a PR comment with the exact phrase:

```
I have read the CLA Document and I hereby sign the CLA
```

That writes their signature file to the current version folder. Commenting
`recheck` re-evaluates without signing.

### `pr.yml` — gate the build

The `check-cla` job does **not** touch Drive. It reads the `CLA` commit status via
the GitHub API and blocks the `build` job until the status is `success`. Reading a
status only needs the read-only `GITHUB_TOKEN`, which is available even on fork
PRs, so no Drive secret is exposed on the build side. A short retry absorbs the
race between the two workflows.

### Commits with no linked GitHub account

If a PR contains a commit whose author email is not tied to any GitHub account,
that author cannot be mapped to a signature and the CLA check **fails**. The
contributor must correct the commit authorship (use a commit email associated with
their GitHub account) and force-push.

### Publishing a new CLA version

Bump the `VERSION x.y.z` line in `CLA.md`. The workflows automatically create the
new `vX.Y.Z` folder and require contributors to sign the new version; prior
signatures stay archived in their old version folders.

---

## Configuration reference

Set under **Settings → Secrets and variables → Actions**:

| Kind         | Name                              | Purpose                                                        |
|--------------|-----------------------------------|----------------------------------------------------------------|
| **Secret**   | `CLA_GDRIVE_SERVICE_ACCOUNT_JSON` | Full JSON key of the service account CI authenticates as       |
| **Variable** | `CLA_GDRIVE_ROOT_ID`              | ID of the Shared Drive folder that holds the `vX.Y.Z` folders  |
| **Variable** | `CLA_ENFORCED`                    | `true` enables the CLA gate; anything else disables it         |

The service account must be a member (Content manager / Editor) of the Shared
Drive, and the **Google Drive API** must be enabled in its Cloud project.

> Treat `CLA_GDRIVE_SERVICE_ACCOUNT_JSON` like a password — it is only ever pasted
> into the GitHub secret field and read by the workflow at runtime. If it is
> exposed, delete that key in the Cloud console and create a new one.
