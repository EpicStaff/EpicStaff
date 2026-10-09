from importlib import import_module


class LazyImport:
    """Proxy that imports a module (or one of its objects) only on first use.

    Stands in for the real object: calling, attribute access, and `isinstance` /
    `issubclass` checks all resolve the import on demand and delegate to it.
    """

    def __init__(self, name: str, package: str | None = None, obj: str | None = None):
        self.name = name
        self.package = package
        self.obj = obj
        self._lazy_obj = None

    @property
    def lazy_obj(self):
        if self._lazy_obj is None:
            obj = import_module(self.name, self.package)
            if self.obj is not None:
                obj = getattr(obj, self.obj)
            self._lazy_obj = obj
        return self._lazy_obj

    def __getattr__(self, name: str):
        return getattr(self.lazy_obj, name)

    def __call__(self, *args, **kwargs):
        return self.lazy_obj(*args, **kwargs)

    def __instancecheck__(self, instance) -> bool:
        return isinstance(instance, self.lazy_obj)

    def __subclasscheck__(self, subclass) -> bool:
        return issubclass(subclass, self.lazy_obj)
