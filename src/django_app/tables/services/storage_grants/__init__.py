"""Per-node storage grants: what a code-running node may do to a flow's attached files.

A grant is three flags (read, write, delete) on a node, or on each code slot of a
classification decision table. File Extractor and Audio to Text have no grant columns:
they always read the flow's files, and writing them needs FILES:READ. Every run
of the flow gives the node's code exactly what its flags say; see `storage_credentials`
for how accounts are minted. Because user code holds the account's credentials, changing
who may edit what the code does is as sensitive as the grant itself, so this package is
the edit lock:

- `slots`: which models carry grants and which of their fields steer the code.
- `errors`: the 403 raised when the actor lacks a permission the grant stands for.
- `actor`: the permissions of whoever writes.
- `write_checks`: the check run before any write of a node.
- `flow_checks`: what a whole flow's grants require (restoring a version).
- `capping`: lowering flags to what an importer or copier holds.
- `tool_lock`: the venv check for graph code sites: what editing a virtualenv requires,
  from the code that runs in it.
"""
