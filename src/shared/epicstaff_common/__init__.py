def resolve_setting(config_globals, name, default=None):
    """Return config_globals[name], or `default` when it's missing or None.

    Pass the calling tool's own `globals()` -- the sandbox seeds a tool's
    args_schema.json config fields as module-level globals, so this is
    always `globals()` at the call site. `False`/`0` are real values and are
    returned as-is; only `None` (how an unfilled, non-required config field
    actually arrives -- PythonCodeToolConfigValidator writes an explicit
    `None`, not a missing key) falls back to `default`.
    """
    value = config_globals.get(name)
    empty_values = (None, "")
    return default if value in empty_values else value


def require_setting(config_globals, name):
    """Return config_globals[name], or raise RuntimeError if it's blank."""
    value = resolve_setting(config_globals, name)
    if not value:
        raise RuntimeError(f"{name} is required but not configured")
    return value


def safe_error_message(error):
    """A message safe to hand back to the agent.

    The literal text for a RuntimeError the tool raised itself (hand-written,
    never carries a secret) -- or just the exception's class name for
    anything else, since str()'ing a third-party exception (SQLAlchemy driver,
    OpenAI SDK, litellm) can echo a query, a connection string, or a key.
    """
    if isinstance(error, RuntimeError):
        return str(error)
    return type(error).__name__
