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
- On every PR, **all commit authors, all co-authors named in
  `Co-authored-by:` trailers, and the person who opened the PR** must have
  signed the **current** CLA version before the build is allowed to run. Only
  allow-listed bots are exempt (see [Bots and the allow-list](#bots-and-the-allow-list)).
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
2. Reads the `Co-authored-by:` trailers of every commit and looks up each
   co-author's GitHub account (see [Co-authors](#co-authors)).
3. Adds the **PR opener** (the account that opened the pull request) to the
   list. Each person is listed once, even if they appear in several roles or
   on several commits.
4. Checks the current version folder in Drive for each person's signature (and
   that the stored hash still matches).
5. Posts or updates a single PR comment listing anyone who still needs to sign,
   and anyone who could not be linked to a GitHub account.
6. Sets a commit status named **`CLA`** (`success` / `failure`) on the PR head
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

### Why the PR opener must sign

A commit is linked to a GitHub account through its git author email, and anyone
can set that email to any value (`git commit --author=...`). On its own, the
commit list does not prove who wrote the code. The PR opener comes from the
GitHub API and cannot be forged, so requiring the opener's signature makes sure
a real person always gives the licence grant, unless an allow-listed bot opened
the PR. If the opener is also a commit author or co-author, they are listed
once.

### Co-authors

A person named in a `Co-authored-by:` trailer is a contributor and must sign
the CLA, like a commit author. Only trailers in the **last paragraph** of the
commit message count (this is where git and GitHub read trailers). Unlike git,
a message whose only paragraph is a trailer also counts — stricter on purpose.
The key is matched without regard to case, so `Co-Authored-By:` works too.

A co-author is linked to a GitHub account only through their **GitHub noreply
email**, which is the email GitHub itself writes into the trailer:

- `<id>+<login>@users.noreply.github.com` — the account is looked up by its
  numeric id. The id never changes, so this still works after the person
  renames their account; the current login is used for the signature.
- `<login>@users.noreply.github.com` — the older form, looked up by login.

Any other email (a work or personal email, or an account that no longer
exists), or a trailer that is not in the form `Name <email>`, cannot be
linked, so the CLA check **fails** and the comment lists the trailer. To fix
it, change the trailer to the co-author's GitHub noreply email (shown in their
GitHub email settings), or remove the trailer, then rewrite the commits and
force-push.

**Lookup limit.** Each co-author costs one GitHub API call, and the workflow
token's rate limit is shared by the whole repository. So at most **20 distinct
co-authors** are looked up per run. Any co-author beyond that is not checked
and fails the CLA check. A PR with more co-authors than that should be split
into smaller PRs. The PR comment lists at most 25 people in each list and adds
"and N more" for the rest.

**AI coding tools.** Tools such as Claude Code or Cursor add trailers like
`Co-Authored-By: Claude <noreply@anthropic.com>`. These emails do not belong to
a GitHub account, so they fail the check on purpose: an AI tool cannot sign
a CLA. There is no ignore list for them — remove the trailer before you push.

Trailers are free text in the commit message: anyone can add one or leave one
out. The co-author check catches honest mistakes; it is the PR opener check
(above) that makes sure a real person always signs.

### Bots and the allow-list

A bot is skipped — as a commit author, as a co-author and as the PR opener —
only when **both** are true:

- its GitHub account type is `Bot`, and
- its login is in the allow-list.

The allow-list defaults to `dependabot[bot]`. Any other bot is treated like a
person: it has no signature, so the check fails. A normal `User` account whose
login matches an allow-list entry is not skipped either.

To change the list, set the `CLA_ALLOWLIST` repo variable to a comma-separated
list of bot logins, for example `dependabot[bot],renovate[bot]`. The value
**replaces** the default, so include `dependabot[bot]` if you still want it.
An unset or empty variable uses the default.

### Commits with no linked GitHub account

If a PR contains a commit whose author email is not tied to any GitHub account,
that author cannot be mapped to a signature and the CLA check **fails**. The
contributor must correct the commit authorship (use a commit email associated with
their GitHub account) and force-push. A co-author who cannot be linked fails the
check the same way — see [Co-authors](#co-authors).

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
| **Variable** | `CLA_ALLOWLIST`                   | Optional. Comma-separated bot logins exempt from signing; unset/empty = `dependabot[bot]` |

The service account must be a member (Content manager / Editor) of the Shared
Drive, and the **Google Drive API** must be enabled in its Cloud project.

> Treat `CLA_GDRIVE_SERVICE_ACCOUNT_JSON` like a password — it is only ever pasted
> into the GitHub secret field and read by the workflow at runtime. If it is
> exposed, delete that key in the Cloud console and create a new one.
