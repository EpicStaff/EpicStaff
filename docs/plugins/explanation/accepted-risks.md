# Accepted risks

This page lists what the plugin platform does not protect against, so that operators can decide
whether, and which, plugins to install. Each limit is a deliberate choice for this version. See
[the plugin lifecycle](lifecycle.md) for what each step does.

## Installing a plugin means trusting its code

A plugin's backend runs its own Python code on the deployment's plugin node, and its page runs
its own code in people's browsers. EpicStaff limits what that code may reach, but it does not
check what it does. "Trusted" means the package is signed with a key the operator trusts;
"Untrusted" only says it is not. Neither says the code is safe: review a plugin, or trust its
publisher, before approving it.

## Plugins on one node share a container

Every plugin backend on a node runs in the same container, each as a process of its own under a
Unix user id of its own. They are separated by process and user permissions only, not by
virtual machines or separate containers.

## What co-located plugins can see of each other

A plugin can see the other plugins' processes, the ports they listen on and their identifiers.
It cannot read their files, their environment, their keys or their data, in their directories or
in their databases.

Two things they still share:

- **UNIX sockets in the abstract namespace.** These have no file, so file permissions do not
  apply: a socket one plugin opens there can be reached by every other plugin on the node. Use a
  socket in your own directory instead, or none.
- **The node's ephemeral ports.** Each plugin holds at most 256 open descriptors, and its new
  connections are capped and rate-limited, but several plugins together could still use up the
  node's ephemeral ports with UDP sockets that are connected and never send. The other plugins
  on the node would then fail to open outbound connections until those sockets close.

## Keeping organizations apart inside a plugin is the plugin's job

EpicStaff keeps each organization's data apart in EpicStaff, and gives a plugin a key per
organization. Inside the plugin's own backend and database, one process serves every
organization it is granted to: keeping their data apart there is up to the plugin's code.

## Declared access covers every item of a type

A plugin's `access` grants actions on a type of resource, such as `flows: read`, across the whole
organization it is granted to. It is not limited to the items the plugin created, except for the
secrets it may refer to.

## "On behalf of" is the plugin's statement

When a backend calls EpicStaff on behalf of a person, EpicStaff checks that the person is a member
who may use the plugin in the organization. It does not check that the person asked for the call.

## Outbound access

A backend reaches only the hosts its manifest declares, over HTTPS on port 443. A change to that
list takes effect within about 30 seconds. A declared host that serves many sites behind one
name lets the plugin reach all of them.

## Soft limits

Some limits are enforced after the fact. A process may briefly use more memory than its cap
before it is stopped, and the database statement timeout is a setting of the plugin's role that
the node puts back when it was changed, rather than a hard limit.

## What a suspension does not stop

A suspension stops runs, keys and people's access at once, but not everything: AI features
outside runs, resources a running step reaches by name, voice conversations already open, and
the plugin's own database and outbound access, which belong to the plugin, not to one
organization. A run that starts in the moment a suspension is being saved may keep running for
up to about a minute before it is stopped. The full list is in
[the plugin lifecycle](lifecycle.md#what-a-suspension-does-not-stop).

## Deleting data

When an organization's plugin data is deleted, EpicStaff deletes everything the plugin created in
EpicStaff, but the plugin deletes its own data. Its organization removed hook can fail, or a
SuperAdmin can skip it: that data then stays where the plugin keeps it until the plugin itself is
deleted. Deleting a plugin deletes its database and its upgrade backups; back up the database volume
first if the data may be needed. Plugin activity is kept after its plugin and its organizations
are gone.

What a plugin created stays the plugin's, even after people in the organization edited it, and
a file a person overwrote under the plugin's name stays the plugin's file. Deleting the plugin's
data in the organization deletes them all, people's edits included: EpicStaff does not hand a
resource over to the organization when someone changes it. Copy what should outlive the plugin.

## Backups hold every organization's data

Before an upgrade runs migrations, the plugin node backs up the plugin's whole database: every
organization's data in it, organizations whose data was deleted since included. That data stays
in the backups until they are deleted: at most the grace period, and only the three latest
upgrades' backups are kept. Backups are deleted with the plugin. They are not encrypted on the
node; the volume and a directory only the node agent can open are the boundary. Copy them off
the host only as carefully as the database itself.

## No automatic rollback, no downgrade

EpicStaff never rolls an upgrade back by itself, and never installs an older version over a
newer one. A failed upgrade waits for a SuperAdmin: retry it, approve a newer version, cancel it
while the database holds no change of the new version, or restore the backup the upgrade took. A
restore loses every change made to the database since that backup.

## Cancel trusts the plugin's own migration ledger

Whether an upgrade can still be cancelled is decided from the migration ledger in the plugin's
database. The plugin's migrations can write to that table, so a plugin can make EpicStaff think
its database holds no change of the new version when it does. Cancelling then starts the old
version on that database.
