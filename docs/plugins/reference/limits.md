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
| `db_connections` | 1–100 | 5 | `PLUGINS_MAX_DB_CONNECTIONS` (20) | No: plugins have no database yet |
| `statement_timeout_seconds` | 1–600 | 30 | `PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS` (60) | No: plugins have no database yet |
| `requests_per_minute` | 1–6000 | 120 | `PLUGINS_MAX_REQUESTS_PER_MINUTE` (600) | No: plugins cannot call EpicStaff's API yet |

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
value. The tab marks the limits this version does not enforce as such.

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

## The whole node

All plugin backends of a deployment share one node container. The operator caps it as a whole
with `ES_PLUGINS_CPUS` and `ES_PLUGINS_MEMORY`. Keep `ES_PLUGINS_MEMORY` above the sum of the
plugins' memory caps: otherwise the kernel, not the node, picks which process to kill, and plugin
processes are marked as its first choice.
