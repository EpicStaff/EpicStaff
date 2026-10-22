# Compatibility and versioning

How EpicStaff orders a plugin's versions, what a new version may and may not change, and what a
SuperAdmin approves when upgrading to it.

## Versions and their order

A plugin's `version` is a [SemVer 2.0](https://semver.org/spec/v2.0.0.html) version. Versions are
ordered by SemVer precedence:

- `1.0.0 < 1.0.1 < 1.1.0 < 2.0.0`, comparing numbers, not text (`1.10.0` is newer than `1.9.0`);
- a pre-release sorts before its release:
  `1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-beta < 1.0.0-rc.1 < 1.0.0`;
- build metadata is ignored: `0.7.0+2` is the same version as `0.7.0`.

The Python SDK compares versions the same way, in `epicstaff_plugin.versions` (`version_key`,
`compare_versions`, `is_newer`), for example in an upgrade hook
([Python SDK](python-sdk.md)).

## A new version must be newer

An installed plugin takes only a newer version. EpicStaff refuses an upload, and an approval, of
a version that is not newer than the plugin's latest approved version: the version being
installed by an open upgrade, else the installed one. That refuses the same version, an older
one, and one that differs only in build metadata, with `409 plugin_version_not_newer`. There
are no downgrades. Uploading a newer version replaces any package of the plugin still waiting
for review.

## What a new version may not change

Checked at upload, before anything is stored, and again at approval:

| Change | Refused with | `loc` |
|---|---|---|
| Dropping the backend the installed version has, or that the target of a failed upgrade added | `409 plugin_upgrade_unavailable` | `manifest.backend` |
| Dropping the database the installed version has, or that the target of a failed upgrade added | `409 plugin_upgrade_unavailable` | `manifest.database` |
| Changing a migration file that is already applied: a file with the name of one of the latest approved package's files, or of an entry in the database's migration ledger, but other content | `409 plugin_upgrade_unavailable` | `package.database/migrations/<name>` |

A version that takes the place of a failed upgrade's target is checked against both the
running version and that target.

A new version may leave out a migration file it no longer needs: the migration runner ignores
ledger entries it has no file for. Add a new file for every change instead
([Write database migrations](../how-to/database-migrations.md)). A plugin that must drop its
backend or database is deleted and installed again.

## What needs the SuperAdmin's approval

The review of a new version compares it with the latest approved version. Each of these is
**new access**: the approval must carry `access_growth_acknowledged: true`, or it is refused with
`400 access_growth_not_acknowledged`.

| Rule | New access when |
|---|---|
| Declared access | The new version declares a `(resource type, action)` pair the baseline does not |
| Outbound hosts | It lists a host the baseline does not. A new wildcard is new even when it covers a host the baseline lists |
| Public paths | It has a rule no baseline rule covers. A baseline rule covers it with the same `path` and `match`, at least its `methods`, and a `rate_limit_per_minute` and `max_body_kb` at least as large. A new path, `exact` changed to `prefix`, more methods or higher limits are new access |

The approval also names the version it was reviewed against (`reviewed_against_package_id`), so a
review that went stale (a newer version took the place of a failed one meanwhile) cannot approve
a different change: it is refused with `409 review_outdated`. An untrusted package always needs
the untrusted acknowledgement, whatever its predecessor was
([Trust and signing](../explanation/trust-and-signing.md)).

The review also shows, without an approval of its own: a change of trust or signer, whether the
plugin goes offline, a backend or database it adds, the migrations it will run, hooks added and
removed, user permissions added, removed or with other defaults, settings added, removed and
needed, the limits that changed, the backup and the database's size, how many organizations go
offline, and whether the upgrade can be cancelled.

## Settings, built-in defaults and custom roles

- **Settings the new version needs.** A required setting with no value and no default, or a
  stored value the new version's rules refuse, is needed: the approval refuses
  (`400 invalid_plugin_settings`, `loc` `settings.<key>`) until it is given, in the approval's
  `settings`. A stored secret counts as valid. Settings given there do not restart the running
  version: the new version starts with them.
- **Settings the new version drops** keep their stored values, but the new version does not
  receive them.
- **Built-in roles** get the new version's defaults.
- **Custom roles** keep what they were given. An action the new version no longer declares is
  ignored, and comes back if a later version declares it again.

## Contract versions

The manifest names the version of each platform contract it is written for (`platform`):
`frame_protocol`, `gateway_context` and `hook_api`. A new version of a plugin may name other
contract versions than its predecessor, as long as this EpicStaff supports them
([EpicStaff plugins](../README.md#compatibility)).

## How an upgrade goes

The SuperAdmin approves the new version. A plugin with a backend keeps running while its node
prepares the new version; then the plugin goes offline, the node backs its database up, runs the
new version's migrations and starts it. Once it runs, each organization is brought to the new
version by the plugin's upgrade hook, and people use it again. EpicStaff never rolls back by
itself: a failed upgrade is retried, replaced by a newer version, cancelled, or its backup
restored. The steps, what people see meanwhile and the SuperAdmin's choices are in [the plugin
lifecycle](../explanation/lifecycle.md#upgrades).
