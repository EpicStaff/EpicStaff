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
deleted. Deleting a plugin deletes its database without a backup; back up the database volume
first if the data may be needed. Plugin activity is kept after its plugin and its organizations
are gone.
