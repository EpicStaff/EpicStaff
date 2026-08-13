from dataclasses import dataclass


@dataclass
class ImportSettings:
    preserve_uuids: bool = False
    replace_existing: bool = False
    import_labels: bool = False
