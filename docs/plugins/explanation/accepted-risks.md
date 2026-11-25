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
- **The node's ephemeral ports.** Every plugin on the node shares its ephemeral ports, 21000 to
  65535, about 44,500 of them. A plugin cannot `bind()` a socket, TCP or UDP, and its new TCP
  connections are capped and rate-limited. The node stops a plugin, and keeps it stopped until a
  SuperAdmin restarts it, when the plugin's user has a TCP socket listening on any port (a
  `listen()` without `bind()`) or holds more than 1,280 network sockets in all, UDP sockets that
  are connected and never send included. TCP connections it accepted on its own port do not
  count. The node checks once a second, so a plugin can press on the ports for up to a second
  before it is stopped ([Runtime](../reference/runtime.md#how-the-backend-is-started)).

## A plugin chooses what EpicStaff's own sidebar shows

While an app is open, EpicStaff's own sidebar shows the app's name, its icon and its menu (`spa.navigation`): labels
and icons the plugin chose, outside the plugin's frame. A label such as "Change password" looks like part of
EpicStaff, although it opens a page of the plugin.

Showing the menu under the app's name and switcher does not protect anyone by itself, because the plugin chooses its
name and icon too. A plugin named "EpicStaff", with an icon like EpicStaff's logo and labels such as "Settings" and
"Change password", can make the whole sidebar look like EpicStaff's own.

What protects people is the SuperAdmin's review. The review of every install and upgrade shows the plugin's name, its
icon and its menu (every entry's icon, label, path and permission, whoever the entry is shown to), and an upgrade that
changes the menu says so. Read them before approving,
and refuse a plugin that looks like EpicStaff or like another app. An upgrade's review shows the new icons, but does not
point out an icon redrawn under the same file name: look at them.

The rules make sure that what the review shows is what people see:

- A label is at most 32 characters of text that shows all it holds: no invisible character (format or default-ignorable
  characters, such as bidirectional overrides, zero-width spaces and fillers), no whitespace but the plain space,
  none at either end, and at least one visible character. So a label cannot reverse, hide or blank out part of its
  text. Two labels of a menu cannot differ only in case or in a look-alike form, such as fullwidth letters, and a
  menu has at most 12 entries.
- Icons pass the same safety checks as the plugin's icon, and menu icons are drawn as one-colour shapes. No icon can
  animate: SMIL animation, CSS animations and transitions are refused, so an icon cannot change while people look at
  it. An icon's file changes only with a new version, whose review shows it.

EpicStaff does not judge what a name or a label says or what an icon shows. An SVG icon can also draw differently
in different places, as its file allows: a CSS media query or a `<switch>` element picks what to draw by the size the
icon is drawn at, the theme or the browser's language, so the review can show a different picture than a member's
sidebar. When that matters, read the icon's SVG source before approving.

An SVG icon can also be built to draw slowly. The checks cap `<use>` elements and refuse chains of them, but not the
other elements that make a browser do much work for a small file: a `<pattern>` tiled across the icon, a `<filter>`
(blurs, lighting, turbulence), or an `<feImage>` that draws another part of the same file. Such an icon slows down
every page that draws it: the Apps list, EpicStaff's sidebar while the app is open, and the review itself. This holds
for the plugin's icon and its menu icons alike. The planned fix is an allow-list of SVG elements and attributes for
both, so that only plain shapes, paths and fills pass. Until then, refuse a plugin whose icons are slow to draw in the
review.

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

## Code runs in the sandbox outside the outbound hosts

A plugin whose access includes `create`, `update` or `use` on flows, or `create` or `update` on
tools, venvs or custom libraries, can have code of its choosing run in EpicStaff's sandbox: by
writing a flow or a tool that holds code, by running a flow, or by choosing the libraries a venv
installs or uploading a custom library package, which then run with all code in a venv that uses
them, the organization's own included. The sandbox has its own network access, and the plugin's
outbound hosts do not apply to that code. So the list a SuperAdmin approves bounds the plugin's
backend, not what its flows and tools can reach. A flow a plugin writes also runs, with its code,
whenever someone in the organization runs it, even when the plugin may not run flows itself. A
tool's code runs whenever an agent calls the tool. The review warns about this
([review warnings](../reference/manifest.md#review-warnings)). Grant `flows` `create`, `update`
or `use`, or `create` or `update` on `tools`, `venvs` or `custom_libraries`, only to a plugin you
would trust with that network access.

Tools `create` or `update` has a second effect: the plugin can point an agent at an MCP server
that is not one of its outbound hosts. The agent, not the plugin's backend, connects to it, so
the outbound hosts do not apply there either.

## A plugin host name belongs to whoever controls its DNS

With a template that has a prefix or a suffix, EpicStaff checks that a plugin's host is served by
this deployment before it sends that host a login code
([The host check](../operator/enable-plugins.md#the-host-check)). The check stops a name in the
zone that points at another server by accident, or that someone else hosts. It does not stop
someone who controls a name in the zone and relays the challenge to this deployment's nginx: that
server passes the check and receives the plugin's users' login codes. Whoever controls a DNS name
controls that origin. Keep control of the zone to people you trust, or use a template without an
affix on a zone of the plugins' own.

## Soft limits

Some limits are enforced after the fact. A process may briefly use more memory than its cap
before it is stopped, and the database statement timeout is a setting of the plugin's role that
the node puts back when it was changed, rather than a hard limit.

The disk cap is measured too, not enforced by the file system. The node measures every 30
seconds, and at once when its free space falls fast, so a plugin can write past its cap by a few
hundred MiB, or for up to 30 seconds while other plugins free space, before it is stopped. No one
file grows past the cap. On a default install the plugin node's volume shares the host's file
system with the database and the rest of EpicStaff, so a plugin that writes at the disk's full
speed when the disk is nearly full can take the free space they need too.

A plugin can also hide what it uses from the measurement. A deleted file whose descriptor the
plugin sent over a UNIX socket and never received belongs to no process, so the node cannot see
it, yet its space stays taken. Each plugin can keep up to 256 such files, each up to its cap: about
512 GiB at the default cap, more than most disks. The node then measures that plugin as almost
empty, and when the free space falls below the floor it stops the other plugins first. Only file
system quotas would close this. So give the node a file system of its own
([Enable plugins](../operator/enable-plugins.md#disk)) wherever its plugins are not all trusted:
a full plugin volume then stops plugins, never the database or the rest of EpicStaff.

## One plugin can restart the shared database server

Every plugin's database lives on one Postgres server, `plugins_db`, whose container has a memory
limit, `PLUGINS_DB_MEMORY`. A plugin can write a query that alone needs more than that limit, for
example by raising its own `work_mem` and sorting or aggregating a large set. The kernel then
kills that query's server process, and Postgres resets to recover from it: every plugin's open
connections drop and its queries in flight fail, in every organization, for the seconds the
recovery takes. Committed data is not lost. A plugin can do this again after every recovery.

What bounds it: the memory limit itself, which keeps the rest of the host safe; the plugin role's
`statement_timeout`, which ends a long query, though a plugin can change it for its own session
(see [Soft limits](#soft-limits)); and the SuperAdmin's review, since the plugin's code issues
the query. The setup wizard (`python scripts/envtool.py --setup`, "Tune performance and limits")
fits `PLUGINS_DB_MEMORY` to the host, 2 GiB by default. An operator who sees `plugins_db`
recovering, with "terminated by signal 9" in its logs, raises `PLUGINS_DB_MEMORY` in `src/.env`
(for example to `4g`), recreates the container with
`docker compose --profile plugins up -d plugins_db`, and finds and removes the plugin that issues
the query.

## What a suspension does not stop

A suspension stops runs, keys and people's access at once, but not everything: the "test"
actions of models and tools, resources a running step reaches by name, the plugin's custom
libraries that the organization's venvs install, voice conversations already open, and the
plugin's own database and outbound access, which belong to the plugin, not to one
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

## Custom library versions and links a plugin does not own

A version of a custom library has no owner of its own: it belongs to whoever owns the library.
A plugin with `custom_libraries` `update` can upload a new version to one of the organization's
own libraries. That version is not the plugin's: deleting the plugin's data does not delete it,
and the organization's venvs that install the library keep installing it. After deleting a
plugin's data, check the versions of the organization's custom libraries it could update, and
remove the ones it uploaded.

A venv names the custom libraries it installs by name, inside the sandbox, not by a link
EpicStaff can follow. So when one of the organization's venvs installs a library the plugin
created, a run of code in that venv is not seen to use the plugin's library: a suspension does
not refuse it.

Deleting the plugin's data does not delete a venv the plugin created that the organization's
code runs in, nor a custom library it created that one of the organization's venvs names: it
hands them over to the organization, and the grant's `grant_purged` activity event lists them
([lifecycle](lifecycle.md#when-the-grace-period-ends)). The plugin chose what such a venv
installs, and the organization keeps running its code with exactly those libraries, the plugin's
own custom library among them. Check what was handed over: the libraries of each venv, and the
versions of each library. What is handed over while the plugin itself is deleted, from an
organization whose grant was already gone, has no event: only the `plugins.purge.handed_over`
line in Django's log names it ([deleting a plugin](lifecycle.md#deleting-a-plugin)).

## A hanging sandbox holds up an organization's storage writes during a purge

Deleting a plugin's data deletes each venv and custom library it owns in the sandbox and its
record in EpicStaff in one transaction, which holds the organization's lock, so a failure
between the two is put right by a later pass. While the sandbox hangs, that transaction waits
for the sandbox client's timeout (`SANDBOX_CLIENT_TIMEOUT`, 30 seconds by default) on each call,
up to two calls per venv or library. Until it gives up, file uploads, restores and other storage
writes in that organization wait too. A pass checks its deadline before each row, so it runs
at most one venv or library past it; each hourly pass does the same while the sandbox hangs.

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
