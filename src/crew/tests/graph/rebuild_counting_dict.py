class RebuildCountingDict(dict):
    """A dict that counts how often an instance of it is constructed.

    Flow variables are dict subclasses (DotDict); a deep copy such as
    `dataclasses.asdict` rebuilds every one of them, so a count above zero after
    sending a message means the message was copied.
    """

    constructions = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).constructions += 1
