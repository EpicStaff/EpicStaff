"""The node lab's stand-in for django_app's node API, plus the controls run.sh drives.

Serves the plugin node exactly the documents of django_app's node API (desired state with an ETag,
packages, runtime credentials, reports), built from the packages the packer wrote to
/packages and the lab's three placements. The runtime files carry this service's own signing
keys, so it can mint the gateway contexts the probe plugins require.

Lab controls (not part of the node API):
- GET  /lab/reports                    the node's last report
- POST /lab/placements/<id>            change a placement (JSON: field -> value; "runtime.x")
- GET  /lab/context?plugin=&path=      a context for GET <path> on that plugin
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from aiohttp import web
from epicstaff_plugin.testing import ContextSigner

NODE_KEY = os.environ["PLUGINS_NODE_KEY"]
PACKAGES = Path("/packages")
ISSUER = "https://epicstaff.lab"

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


def desired_state() -> dict:
    body = {"format": 1, "node": {"name": "lab-node"}, "placements": list(placements.values())}
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
            "service_accounts": {},
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
    return web.json_response({"code": "not_found"}, status=404)


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
app.router.add_route("*", "/api/{tail:.*}", node_api)

if __name__ == "__main__":
    web.run_app(app, port=8000, access_log=None, print=None)
