from importlib import import_module

__all__ = ["LazyImport"]


class LazyImport:
    """Defer an import until the wrapped module or object is actually used.

    Calling the instance or reading an attribute off it imports `module` (once, cached)
    and forwards to the real object. A bare reference to the instance itself does not:
    naming it in an `except` clause, for example, reads it straight off the module's
    `__dict__` and never reaches `__call__`/`__getattr__`. Wrap the containing module
    (`object=None`) and reach the class through an attribute (`boto3_exceptions.ClientError`)
    for anything used that way, rather than binding one class to its own `LazyImport`.
    """

    def __init__(self, module: str, object: str | None = None, package: str | None = None):
        """Record where to import from without importing yet.

        Args:
            module: Dotted module path, e.g. `"botocore.exceptions"`.
            object: Attribute to pull out of `module` once it is imported. Omit to wrap
                the module itself.
            package: Anchor package for a relative `module`, forwarded to `import_module`.
        """
        self._module = module
        self._object = object
        self._package = package

        self._lazy_value = None
        self._is_loaded = False

    @property
    def lazy_value(self):
        """The wrapped module or object, imported and cached on first access."""
        if self._lazy_value is None:
            module = import_module(self._module, self._package)
            if self._object is not None:
                self._lazy_value = getattr(module, self._object)
            else:
                self._lazy_value = module
        return self._lazy_value

    def __call__(self, *args, **kwargs):
        """Import the wrapped object if needed, then call it with `args`/`kwargs`."""
        return self.lazy_value(*args, **kwargs)

    def __getattr__(self, name: str):
        """Import the wrapped object if needed, then return its `name` attribute."""
        return getattr(self.lazy_value, name)
