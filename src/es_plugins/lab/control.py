"""The node lab's stand-in for django_app's node API, plus the controls run.sh drives.

Serves the plugin node exactly the documents of django_app's node API (desired state with an ETag,
packages, runtime credentials, reports, hook job claims and results), built from the packages
the packer wrote to /packages and the lab's three placements. The runtime files carry this
service's own signing keys, so it can mint the gateway contexts and hook assertions the probe
plugins require.

Lab controls (not part of the node API):
- GET  /lab/reports                    the node's last report
- POST /lab/placements/<id>            change a placement (JSON: field -> value; "runtime.x")
- GET  /lab/context?plugin=&path=      a context for GET <path> on that plugin
- POST /lab/service-accounts/<id>      the organizations a placement's runtime file holds a key
                                       for (JSON list of ids; takes effect at the next fetch)
- POST /lab/hook-jobs                  add a pending install job (JSON: placement_id, job_id,
                                       organization_id)
- GET  /lab/hook-jobs                  every job: its state, claims and the result the node posted
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from aiohttp import web
from epicstaff_plugin.contracts.hook_api import HOOK_HEADER
from epicstaff_plugin.testing import ContextSigner, HookSigner

NODE_KEY = os.environ["PLUGINS_NODE_KEY"]
PACKAGES = Path("/packages")
ISSUER = "https://epicstaff.lab"
# The key every lab service account holds; run.sh checks it never reaches the node's log.
SERVICE_ACCOUNT_KEY = "esp-" + "lab" * 14 + "k"
HOOK_TIMEOUT_SECONDS = 60

PLUGINS = {
    "probe-a": {
        "placement_id": 1,
        "package_id": 1,
        "port": 20001,
        "uid": 20001,
        "memory_mb": 128,
        "cpu_priority": "normal",
    },
    "probe-b": {
        "placement_id": 2,
        "package_id": 2,
        "port": 20002,
        "uid": 20002,
        "memory_mb": 256,
        "cpu_priority": "low",
    },
    # Its package carries a hostile wheel: the node must refuse to install it.
    "probe-evil": {
        "placement_id": 3,
        "package_id": 3,
        "port": 20003,
        "uid": 20003,
        "memory_mb": 128,
        "cpu_priority": "normal",
    },
}
signers = {
    identifier: ContextSigner(plugin_identifier=identifier, plugin_version="1.0.0", issuer=ISSUER)
    for identifier in PLUGINS
}
placements: dict[int, dict] = {}
last_report: dict = {}
# placement id -> the organizations its runtime file lists in service_accounts.
service_account_orgs: dict[int, list[int]] = {1: [7]}
# job id -> {placement_id, kind, organization_id, state, attempt, claims, result}
hook_jobs: dict[int, dict] = {}


def build_placements() -> None:
    for identifier, plugin in PLUGINS.items():
        package = (PACKAGES / f"{identifier}.esplugin").read_bytes()
        placements[plugin["placement_id"]] = {
            "placement_id": plugin["placement_id"],
            "plugin_identifier": identifier,
            "desired_state": "running",
            "restart_generation": 0,
            "package": {
                "package_id": plugin["package_id"],
                "version": "1.0.0",
                "sha256": hashlib.sha256(package).hexdigest(),
                "size": len(package),
                "trust": "untrusted",
                "signer_public_key": None,
            },
            "runtime": {
                "python": "3.13",
                "entrypoint": "probe_plugin.app:app",
                "port": plugin["port"],
                "unix_uid": plugin["uid"],
                "memory_mb": plugin["memory_mb"],
                "cpu_priority": plugin["cpu_priority"],
            },
            "credentials_revision": "0" * 64,
            "settings_revision": 0,
        }


def pending_hook_jobs(placement_id: int) -> list[dict]:
    return [
        {"job_id": job_id, "kind": job["kind"], "organization_id": job["organization_id"]}
        for job_id, job in sorted(hook_jobs.items())
        if job["placement_id"] == placement_id and job["state"] == "pending"
    ]


def desired_state() -> dict:
    listed = [
        {**placement, "hook_jobs": pending_hook_jobs(placement_id)}
        for placement_id, placement in placements.items()
    ]
    body = {"format": 1, "node": {"name": "lab-node"}, "placements": listed}
    revision = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {**body, "revision": revision, "generated_at": datetime.now(UTC).isoformat()}


def authorized(request: web.Request) -> bool:
    return request.headers.get("Authorization") == f"PluginNodeKey {NODE_KEY}"


async def node_api(request: web.Request) -> web.Response:
    if not authorized(request):
        return web.json_response({"code": "node_not_authenticated"}, status=401)
    parts = request.path.strip("/").split("/")[1:]
    if parts == ["plugin-nodes", "self", "desired-state"]:
        document = desired_state()
        etag = f'"{document["revision"]}"'
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304)
        return web.json_response(document, headers={"ETag": etag})
    if parts[:3] == ["plugin-nodes", "self", "packages"]:
        identifier = next(i for i, p in PLUGINS.items() if p["package_id"] == int(parts[3]))
        package = (PACKAGES / f"{identifier}.esplugin").read_bytes()
        return web.Response(
            body=package,
            content_type="application/octet-stream",
            headers={"X-Package-Sha256": hashlib.sha256(package).hexdigest()},
        )
    if parts[:3] == ["plugin-nodes", "self", "placements"]:
        placement = placements[int(parts[3])]
        identifier = placement["plugin_identifier"]
        runtime_file = {
            "format": 1,
            "plugin": {"identifier": identifier, "version": "1.0.0"},
            "issuer": ISSUER,
            "public_url": f"https://{identifier}.plugins.epicstaff.lab",
            "epicstaff_public_url": ISSUER,
            "epicstaff_api_url": "http://control:8000/api/",
            "settings": {"credentials_revision": placement["credentials_revision"][:8]},
            "secret_settings": {"token": f"{identifier}-secret-token"},
            "service_accounts": {
                str(organization_id): {
                    "key": SERVICE_ACCOUNT_KEY,
                    "org_name": f"Lab organization {organization_id}",
                    "grant_state": "granting",
                }
                for organization_id in service_account_orgs.get(placement["placement_id"], [])
            },
            "jwks": signers[identifier].jwks.model_dump(mode="json"),
            "public_paths": [],
        }
        return web.json_response(
            {
                "placement_id": placement["placement_id"],
                "credentials_revision": placement["credentials_revision"],
                "settings_revision": placement["settings_revision"],
                "runtime_file": runtime_file,
            }
        )
    if parts == ["plugin-nodes", "self", "reports"]:
        last_report.clear()
        last_report.update(await request.json())
        return web.Response(status=204)
    if parts[:3] == ["plugin-nodes", "self", "hook-jobs"] and request.method == "POST":
        return await hook_job(int(parts[3]), parts[4], request)
    return web.json_response({"code": "not_found"}, status=404)


async def hook_job(job_id: int, action: str, request: web.Request) -> web.Response:
    """Claim (a fresh assertion bound to the body, as django_app signs it) or take a result."""
    job = hook_jobs.get(job_id)
    if job is None:
        return web.json_response({"code": "hook_job_not_found"}, status=404)
    if action == "claim":
        job["claims"] += 1
        if job["state"] != "pending":
            return web.json_response({"code": "hook_job_not_claimable"}, status=409)
        job["state"], job["attempt"] = "running", job["attempt"] + 1
        identifier = placements[job["placement_id"]]["plugin_identifier"]
        call = HookSigner(signers[identifier]).call(
            job["kind"],
            org={
                "id": job["organization_id"],
                "name": f"Lab organization {job['organization_id']}",
            },
            job_id=job_id,
            attempt=job["attempt"],
            timeout_seconds=HOOK_TIMEOUT_SECONDS,
        )
        return web.json_response(
            {
                "job_id": job_id,
                "kind": job["kind"],
                "attempt": job["attempt"],
                "organization_id": job["organization_id"],
                "timeout_seconds": HOOK_TIMEOUT_SECONDS,
                "assertion": call.headers[HOOK_HEADER],
                "body": call.body.decode("utf-8"),
            },
            headers={"Cache-Control": "no-store"},
        )
    result = await request.json()
    if job["state"] != "running" or result.get("attempt") != job["attempt"]:
        return web.json_response({"code": "hook_job_not_running"}, status=409)
    job["state"] = "succeeded" if result["outcome"] == "succeeded" else "failed"
    job["result"] = result
    return web.Response(status=204)


async def lab_reports(request: web.Request) -> web.Response:
    return web.json_response(last_report)


async def lab_change(request: web.Request) -> web.Response:
    placement = placements[int(request.match_info["placement_id"])]
    for key, value in (await request.json()).items():
        section, _, field = key.partition(".")
        if field:
            placement[section] = {**placement[section], field: value}
        else:
            placement[key] = value
    return web.json_response(placement)


async def lab_service_accounts(request: web.Request) -> web.Response:
    service_account_orgs[int(request.match_info["placement_id"])] = await request.json()
    return web.json_response(service_account_orgs)


async def lab_add_hook_job(request: web.Request) -> web.Response:
    job = await request.json()
    hook_jobs[job["job_id"]] = {
        "placement_id": job["placement_id"],
        "kind": "install",
        "organization_id": job["organization_id"],
        "state": "pending",
        "attempt": 0,
        "claims": 0,
        "result": None,
    }
    return web.json_response(hook_jobs[job["job_id"]])


async def lab_hook_jobs(request: web.Request) -> web.Response:
    return web.json_response({str(job_id): job for job_id, job in hook_jobs.items()})


async def lab_context(request: web.Request) -> web.Response:
    signer = signers[request.query["plugin"]]
    return web.Response(
        text=signer.issue(request.query.get("method", "GET"), request.query["path"])
    )


build_placements()
app = web.Application(client_max_size=1024 * 1024 * 1024)
app.router.add_get("/lab/reports", lab_reports)
app.router.add_post("/lab/placements/{placement_id}", lab_change)
app.router.add_get("/lab/context", lab_context)
app.router.add_post("/lab/service-accounts/{placement_id}", lab_service_accounts)
app.router.add_post("/lab/hook-jobs", lab_add_hook_job)
app.router.add_get("/lab/hook-jobs", lab_hook_jobs)
app.router.add_route("*", "/api/{tail:.*}", node_api)

if __name__ == "__main__":
    web.run_app(app, port=8000, access_log=None, print=None)
