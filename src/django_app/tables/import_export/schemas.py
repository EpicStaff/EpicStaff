from dataclasses import dataclass


@dataclass
class ImportSettings:
    preserve_uuids: bool = False
    replace_existing: bool = False
    import_labels: bool = False
    # Entity types that are always created, never matched to an existing row of
    # the org. A plugin install sets this so suspending or deleting the plugin
    # can never reach the org's own configs, agents or tools.
    force_create_types: frozenset = frozenset()
