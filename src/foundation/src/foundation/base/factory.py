class Factory[Key]:
    """A keyed factory: subclasses register under a key, then are built by key."""

    def __init_subclass__(cls) -> None:
        cls._register: dict[Key, type[Factory]] = {}
        return super().__init_subclass__()

    @classmethod
    def build(cls, key: Key, **init_kwargs) -> "Factory":
        """Build the subclass registered under ``key`` with ``init_kwargs``.

        Raises:
            KeyError: No subclass is registered for ``key``.
        """
        return cls._register[key](**init_kwargs)

    @classmethod
    def registry(cls, key: Key, klass: type["Factory"]):
        """Register ``klass`` under ``key``.

        Raises:
            ValueError: ``key`` is already registered.
        """
        if cls.has(key):
            raise ValueError("This key is occupation.")
        cls._register[key] = klass

    @classmethod
    def has(cls, key: Key) -> bool:
        """Return whether a subclass is registered under ``key``."""
        return key in cls._register
