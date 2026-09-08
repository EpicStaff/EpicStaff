# Dependency Scan Reports — How It Works

The `Dependency scan` workflow finds dependencies with known vulnerabilities. Its
findings are stored in a private **Google Shared Drive**, not published on the
pull request.

---

## Why the report is not public

This repository is **public**, and on a public repository three things are
world-readable to anyone, with no GitHub account required:

- the workflow **run summary**,
- workflow **artifacts**,
- the raw **job log**.

A full Trivy report is a ranked, versioned list of exploitable dependencies with
CVE identifiers and the exact service each one sits in. Publishing it hands an
attacker the reconnaissance step for free — and it is worse than an attacker
scanning us themselves, because it confirms which findings are real and current.

So the workflow publishes only a one-line pointer saying whether the report was
stored. The findings go to Drive. Trivy is configured with `output:`, which keeps
the table out of the job log as well.

> This is the one part of the vulnerability-disclosure work that is deliberately
> **not** public. `SECURITY.md` and `/.well-known/security.txt` are meant to be
> found; this report is not.

---

## Storage layout

One plain-text file per run, in a month folder so the directory stays navigable:

```
<SECURITY_GDRIVE_ROOT_ID>/        # a folder in the Shared Drive
├── 2026-08/
│   ├── 2026-08-31T090359Z-pull_request-33370921430.txt
│   └── 2026-08-31T060012Z-schedule-33370999001.txt
└── 2026-09/
    └── ...
```

The file name is `{UTC timestamp}-{event}-{run id}.txt`, so runs sort
chronologically and each maps back to exactly one Actions run. Each report begins
with a header naming the repo, ref, commit sha, event and run URL, then two
sections:

**Section 1 - actionable.** HIGH and CRITICAL advisories that have a fix
available upstream. This is the section to work from, and the only one that maps
to work someone can do today.

**Section 2 - complete record.** Every known advisory at every severity,
including those with no fix available. It is a **superset** of Section 1, not an
addition to it -- the two counts must never be summed.

Section 2 exists because the first dependency audit counted advisories the way
Section 2 does, and a gate that reports only fixable HIGH/CRITICAL is silent on
the rest. Keeping both in one file means the number someone quotes can be traced
to a definition. Nothing in either section is a confirmed exposure: these are
advisories against locked versions, not reachability findings.

Nothing is ever overwritten — each run writes a new file. Prune old months by
hand if the folder grows.

---

## Configuration reference

Set under **Settings → Secrets and variables → Actions**:

| Kind         | Name                                   | Purpose                                                     |
|--------------|----------------------------------------|-------------------------------------------------------------|
| **Secret**   | `SECURITY_GDRIVE_SERVICE_ACCOUNT_JSON` | Full JSON key of the service account CI authenticates as    |
| **Variable** | `SECURITY_GDRIVE_ROOT_ID`              | ID of the Shared Drive folder that holds the month folders  |

If either is missing or unusable, the upload step fails and stores nothing. That
is intentional: a scan whose report goes nowhere must not report success.

Setup, once per folder:

1. Create a folder in the organization's Shared Drive, e.g. `EpicStaff Security
   Scans`. Access should be narrower than the CLA folder — scan reports are
   sensitive, CLA signatures are merely private.
2. Add the service account as a member with **Content manager** (Editor).
3. Copy the folder id from its URL
   (`https://drive.google.com/drive/folders/<THIS PART>`) into the
   `SECURITY_GDRIVE_ROOT_ID` **variable**.
4. Paste the service-account JSON key into the
   `SECURITY_GDRIVE_SERVICE_ACCOUNT_JSON` **secret**.

The service account must be a Shared Drive member and the **Google Drive API**
must be enabled in its Cloud project — a service account has no personal storage
quota, so an ordinary "My Drive" folder will not work.

You may reuse the same service account as the CLA flow, but store its key under
the name above rather than pointing at `CLA_GDRIVE_SERVICE_ACCOUNT_JSON`, so the
two can be rotated and revoked independently.

> Treat `SECURITY_GDRIVE_SERVICE_ACCOUNT_JSON` like a password. If it leaks,
> delete that key in the Cloud console and create a new one.

---

## Troubleshooting

### `File not found: <folder id>` (HTTP 404) on upload

The service account cannot **see** the folder. Drive answers 404 rather than 403
for anything the caller has no access to, so a permissions problem and a wrong id
look identical from the outside — and a well-formed id is far more often an access
problem.

Check, in this order:

1. **Is the service account shared on the folder?** Take `client_email` from the
   JSON key and confirm that address appears in the folder's sharing list (or is a
   member of the Shared Drive) with **Content manager**. The upload step prints
   this address on failure, so the job log names the account to look for. Adding a
   *person* to the folder does nothing for CI.
2. **Is the folder inside the organization Shared Drive?** A folder in someone's
   My Drive cannot be written to by a service account — it has no storage quota of
   its own. The preflight check reports this case separately.
3. **Is `SECURITY_GDRIVE_ROOT_ID` the folder id, not the Shared Drive id?** Folder
   ids are 33 characters and start with `1`; Shared Drive ids are shorter and start
   with `0A`. Copy it from the folder URL:
   `https://drive.google.com/drive/folders/<THIS PART>`.
4. **Is the key the one you think it is?** If you created a *new* service account
   for this folder rather than reusing the CLA one, the new account needs its own
   grant — the CLA folder working proves nothing about this one.

A preflight check runs before any upload and reports which of these applies, so
the job log should name the cause directly rather than failing mid-upload.

---

## Shared dependency floor

The services keep their own lockfiles, which is correct -- they have different
dependency sets. What was missing is a **shared floor**: a CVE fix had to land in
up to nine places and nothing reported whether it landed in all of them, so real
exposure was set by the oldest pin while everyone read the newest.

`.github/dependency-floor.toml` pins a minimum version for the shared
security-critical packages. Poetry has no constraints-file mechanism and most of
these packages are transitive, so the floor is not consumed by the resolver --
`.github/scripts/check_dependency_floor.py` enforces it by reading every
`src/*/poetry.lock` and failing the build when a service resolves below it.

Floors are set to a version **already shipped somewhere in this repository**, so
raising a lagging service to the floor adds no new supply-chain surface.

### When a CVE fix lands — you do not have to edit this file

The effective target for a package is the **higher of** its recorded floor and
the highest version any service already resolves. So fixing a package in one
service automatically raises the bar for every other service that ships it, and
the check fails naming the laggards. Forgetting to touch `dependency-floor.toml`
cannot hide drift — which matters, because a mechanism that depends on everyone
remembering is the thing that failed in the first place.

Editing the file is therefore only for deliberate policy:

- **Raising a recorded floor** so a version can never be dropped again, even if
  every service downgrades together. Run
  `python .github/scripts/check_dependency_floor.py --update` to set the floors
  to what is currently shipped, rather than hand-editing them. Note that
  `--update` is not an escape hatch: it raises the recorded floors, but any
  service still behind stays flagged.
- **Adding a package** to police, or an `[[exception]]`.

The advisory scan tells you a package is vulnerable; this check tells you whether
the fix reached everywhere that ships it.

### Exceptions

A service that cannot reach the floor gets an `[[exception]]` entry naming the
upstream cap that blocks it. Exceptions are printed on every run, so they stay
visible rather than becoming invisible debt.

The check also fails on a **stale** exception -- one whose gap has since closed.
Otherwise a spent exception would sit there silently excusing a future
regression.

Unlike the advisory scan, this check **fails the job**. It is deterministic, it
is currently green, and a failure means a specific fix did not land everywhere.

---

## Fork pull requests

GitHub does not expose secrets to workflows triggered by a pull request from a
fork. The upload step is therefore skipped for fork PRs, and the run summary says
so. It deliberately does **not** fall back to publishing the report — that would
turn any outside contributor's PR into a disclosure.

Findings introduced by a fork PR are caught by the next run on a branch in this
repository, or by the Monday schedule. If you need one sooner, re-run the scan
from a branch here.

---

## Reading a report

The workflow is **report-only** — it does not fail a pull request on findings
(see the comments in `.github/workflows/dependency-scan.yml` for how to change
that). To review the current state without waiting for a PR, run the workflow
manually from the Actions tab and read the newest file in Drive.
