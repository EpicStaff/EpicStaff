# Use settings

Settings are values a SuperAdmin fills in for your plugin on its **Settings** tab: an API token,
the units to show, the address of a service. They are deployment-wide (one value per plugin, the
same for every organization) and reach only your backend's process.

## Declare them

```json
"settings": [
  { "key": "units", "type": "enum", "label": "Units", "description": "Units for every organization.",
    "required": true, "default": "metric", "values": ["metric", "imperial"] },
  { "key": "forecast_api_token", "type": "secret", "label": "Forecast API token",
    "description": "Token for the forecast provider.", "required": false }
]
```

Settings need a `backend` section. `key` is `^[a-z][a-z0-9_]{0,63}$` and unique. A `secret` has no
`default`; an `enum` must list its `values`, and its `default` must be one of them.

## Types and the values a SuperAdmin may enter

| Type | Form control | Accepted value |
|---|---|---|
| `string` | Text field | Text of at most 1000 characters |
| `text` | Text area | Text of at most 10 000 characters |
| `integer` | Number field | A whole number between −2^53 and 2^53 |
| `boolean` | Toggle | `true` or `false` |
| `url` | Text field | An `http://` or `https://` address of at most 2000 characters |
| `enum` | Select | One of `values` |
| `secret` | Write-only field | 1–4096 characters (and at most 8 KiB as UTF-8) |

A value of the wrong type or size is refused with `400 invalid_plugin_settings`, located at
`values.<key>`.

## Required settings and defaults

- A setting without a stored value uses its `default`, if it has one.
- A **required** setting without a default must be filled in before your backend can start: until
  then the Runtime tab shows the plugin as blocked (`required_settings_missing`), the node keeps
  the process stopped, and the gateway answers `503 plugin_unavailable`. Give required settings
  a sensible default when there is one.
- A required setting without a default cannot be cleared once it is set.

## Secrets

A secret is stored encrypted. The admin page never shows it again after it is saved: only that it
is set and, for a value of at least 9 characters, its last 4 characters. It is decrypted in one
place only, the runtime file EpicStaff hands your plugin's node, which is readable by your
plugin's Unix user alone. Changes are recorded by key, never by value.

## Read them in your backend

Your process gets every setting in its runtime file: non-secret settings with their value or
default (an optional one with neither is left out), and the secrets that are set. With the
[Python SDK](../reference/python-sdk.md):

```python
from epicstaff_plugin.runtime import runtime_config

units = runtime_config().setting("units")  # value or manifest default
token = runtime_config().secret_setting("forecast_api_token")  # None when not set
```

Saving any change restarts your process with the new values; saving a secret always counts as a
change, because EpicStaff never decrypts a stored secret to compare it. Read settings when you
need them or at start-up; there is no change event. Never log a secret, put it in a URL or a command line,
or send it to the browser.
