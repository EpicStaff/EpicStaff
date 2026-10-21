#!/bin/sh
# Packs the probe plugins with real wheels: the only step of the lab that needs the network. Runs
# in the packer container; writes /packages/<id>.esplugin.
#   probe-a      for this machine's architecture only;
#   probe-b      for the SDK's default platforms, x86_64 and aarch64: the node must pick the
#                wheels that fit it from a package that also carries the other architecture's;
#   probe-evil   probe-a plus a hostile wheel (make_evil_wheel.py): its install must fail
#                without the agent ever running the plugin's code.
set -eu
architecture=$(uname -m)
work=$(mktemp -d)
uv build --quiet --wheel /opt/plugin_sdk -o "$work/sdk"
python3 /lab/make_evil_wheel.py "$work/evil" > /dev/null
for identifier in probe-a probe-b probe-evil; do
  source="$work/$identifier"
  cp -r /lab/probe_plugin "$source"
  python3 - "$identifier" "$source/manifest.json" <<'PY'
import json, sys
identifier, path = sys.argv[1:]
json.dump({
    "manifest_version": 1,
    "id": identifier,
    "version": "1.0.0",
    "name": f"Lab {identifier}",
    "description": "Reports what the plugin node lets a plugin process see and do.",
    "publisher": {"name": "EpicStaff"},
    "icon": "icon.svg",
    "platform": {"frame_protocol": 1, "gateway_context": 1, "hook_api": 1},
    "spa": {"entry": "index.html"},
    "backend": {"python": "3.13", "entrypoint": "probe_plugin.app:app"},
    "user_permissions": [{
        "action": "read",
        "description": "Use the probe.",
        "defaults": {"org_admin": True, "member": False, "viewer": False},
    }],
}, open(path, "w"))
PY
  (cd "$source" && uv pip compile --quiet backend/requirements.in --universal --python-version 3.13 \
    --generate-hashes -o backend/requirements.lock)
  case "$identifier" in
    probe-a) set -- --platform "manylinux_2_28_$architecture" ;;
    probe-b) set -- ;;
    probe-evil) set -- --platform "manylinux_2_28_$architecture" --local-wheel "$work"/evil/*.whl ;;
  esac
  epicstaff-plugin pack "$source" --spa-dir /lab/probe_spa --download-wheels "$@" \
    --local-wheel "$work"/sdk/*.whl --out "/packages/$identifier.esplugin" > /dev/null
  echo "packed $identifier: $(wc -c < "/packages/$identifier.esplugin") bytes"
done
