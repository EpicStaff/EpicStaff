# Limits

A plugin backend asks for its resource limits in the manifest. The deployment caps what any
plugin may ask for, and a SuperAdmin can lower the limits of one plugin further. This page lists
the limits, how the one that applies is worked out, and which of them this version of EpicStaff
actually enforces.

## The limits

| Limit | Manifest bounds | Default when the manifest leaves it out | Platform maximum (operator setting) | Enforced in this version |
|---|---|---|---|---|
| `memory_mb` | 64–8192 | 256 | `PLUGINS_MAX_PROCESS_MEMORY_MB` (1024) | Yes, by the plugin node (see below) |
| `cpu_priority` | `normal` or `low` | `normal` | — | Yes: `normal` runs at nice 0, `low` at nice 10 |
| `db_connections` | 1–100 | 5 | `PLUGINS_MAX_DB_CONNECTIONS` (20) | Yes, for a plugin with a database: a hard limit on its connections (see below) |
| `statement_timeout_seconds` | 1–600 | 30 | `PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS` (60) | Yes, for a plugin with a database: a default the platform restores (see below) |
| `requests_per_minute` | 1–6000 | 120 | `PLUGINS_MAX_REQUESTS_PER_MINUTE` (600) | Yes, by EpicStaff's API, per organization (see below) |

`limits` and each of its fields are optional. A limit the manifest leaves out (or sets to `null`)
gets the default above, lowered to the platform maximum if that is smaller. A limit the manifest
names must be within the platform maximum when the package is uploaded.

Public paths have caps of their own, checked the same way: each path's `rate_limit_per_minute`
must be at most `PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE` (120), and its `max_body_kb` at most
`PLUGINS_MAX_REQUEST_BODY_MB` (20) × 1024. See [Public paths](../how-to/public-paths.md).

## When the maximums are checked

A package that asks for more than a platform maximum is refused at upload with
`400 invalid_plugin`, one problem per limit, for example
`manifest.limits.memory_mb: asks for 2048; this EpicStaff allows at most 1024`. The maximums are
checked again when the package is approved, as they are then: an operator who lowered one in
between gets the same error at approval.

## The limit that applies

The SuperAdmin sees four views of each limit on the plugin's **Limits** tab:

- **requested**: what the manifest asks for (or the defaults);
- **platform maximum**: the operator setting;
- **override**: a lower value the SuperAdmin set for this plugin, if any;
- **effective**: the lowest of the three. For `cpu_priority`, `low` when the manifest or the
  override says `low`.

An override can only lower a limit: it must be a positive whole number no higher than the lower
of the requested value and the platform maximum, and `cpu_priority` can only be overridden to
`low`. Removing the override returns the plugin to its requested value. If an operator lowers a
platform maximum below what a running plugin asked for, the effective limit drops with it.

Changing the effective `memory_mb` or `cpu_priority` restarts the plugin's process with the new
value. Changing the effective `db_connections` or `statement_timeout_seconds` of a plugin with a
database does too, once the plugin node has applied the new value to the database. For a plugin
without a database, the tab shows the two database limits as not applying.

## How the request rate is enforced

`requests_per_minute` caps the calls a plugin's backend makes to EpicStaff's API with the
service-account key of one organization (see the [service account API](service-account-api.md)).
Each organization the plugin is granted to counts separately, in a fixed one-minute window that
starts on the minute. Every endpoint counts, the upload stream and `/api/plugin-runtime/` too.
A call over the rate gets `429 throttled` with `Retry-After` set to the seconds left in the
minute; wait that long before calling again. The rate is the effective limit, so a SuperAdmin's
override applies at once. People's requests and API keys are never counted against a plugin.

## How the database limits are enforced

Both apply only to a plugin with a database ([Plugin database](database.md)), to the role its
backend connects as.

- **`db_connections` is a hard limit.** It is the role's connection limit: the database server
  refuses a connection beyond it. Your backend reads the value from
  `EPICSTAFF_PLUGIN_DB_CONNECTIONS`; size your connection pool to it.
- **Open connections, logged in or not.** The plugin node also lets the backend have at most
  `PLUGINS_MAX_DB_CONNECTIONS` connections open to the database server at once, counted before
  they log in, so a plugin cannot fill the server's slots with connections that never
  authenticate. One over it is refused at once.
- **`statement_timeout_seconds` is a default.** It is the role's `statement_timeout`, so a
  statement that runs longer is cancelled. Your backend may change it for its own sessions (`SET
  statement_timeout`), and a migration may set a default on its database with `ALTER DATABASE …
  SET`. A change to the role's own setting, by the plugin or anyone else, is put back by the
  plugin node within about a minute; the Runtime tab then shows when, and the plugin's activity
  records it at most once an hour.

## How memory is enforced

Every 2 seconds the plugin node adds up the memory the plugin's processes allocated, over **every
process running under the plugin's Unix user**: the server process and anything it starts,
including processes it detached. It counts each process's anonymous and shared pages
(`RssAnon + RssShmem`), not the interpreter and libraries each process maps from disk, so a
forked worker is not charged again for the code it shares with its parent. Copy-on-write pages
a worker has written to count in that worker. Memory a plugin keeps in a file in memory that no
process maps (a `memfd`, for example) is not counted here, only in the node's
`ES_PLUGINS_MEMORY`; and `/dev/shm` is read-only, so plugins have no POSIX shared memory, which
`multiprocessing.shared_memory` and `multiprocessing`'s locks, queues and pools need. When the
sum is above the effective `memory_mb`,
the node kills every process of that user and starts the plugin again, waiting longer after each
restart (1 s, up to 5 minutes).

This is a soft cap. Between two measurements a process can allocate freely, so it can overshoot
the cap by about its allocation rate × 2 s before it is stopped. Size `memory_mb` for your normal
peak with headroom; a plugin restarted 10 times in a row without staying healthy for a minute
in between is marked failed and stays stopped until a SuperAdmin restarts it from the Runtime tab.

## Disk

The operator caps the disk every plugin backend's own files may use, the same for every plugin:
`ES_PLUGINS_DISK_MB_PER_PLUGIN` (2048 MiB by default) and `ES_PLUGINS_FILES_PER_PLUGIN`
(100,000 files, directories and links). Every 30 seconds the plugin node measures the plugin's
HOME, its TMPDIR included, and the deleted files its processes still hold open. A plugin above
either cap is stopped and marked failed at once, without restarts, and stays stopped until a
SuperAdmin restarts it from the Runtime tab after space was freed. Keep caches small and
delete temporary files when done.

## Connections

Every plugin backend on a node shares the node's network, and with it its local ports. The plugin
node limits each backend, by its Unix user:

| Limit | Value | Over it |
|---|---|---|
| New TCP connections, to anywhere | 200 a second, after a burst of 200 | Refused at once (a TCP reset) |
| TCP connections open at once, to anywhere | 512 | Refused at once |
| Connections open to the database server | `PLUGINS_MAX_DB_CONNECTIONS` (20) | Refused at once |
| Connections open to the egress proxy | 64 | Refused at once |
| Network sockets held, TCP and UDP together | 512 | The plugin is stopped, within a second, until a SuperAdmin restarts it |
| Listening on a port of its own | Not allowed: `bind()` is refused, and a `listen()` without it is caught | The plugin is stopped, within a second, until a SuperAdmin restarts it |

Closed connections stop counting at once. Reuse connections (an HTTP client with a connection
pool, a database pool) rather than opening one per request. The node's own connections are not
limited.

## The whole node

All plugin backends of a deployment share one node container. The operator caps it as a whole
with `ES_PLUGINS_CPUS` and `ES_PLUGINS_MEMORY`. Keep `ES_PLUGINS_MEMORY` above the sum of the
plugins' memory caps: otherwise the kernel, not the node, picks which process to kill, and plugin
processes are marked as its first choice.
