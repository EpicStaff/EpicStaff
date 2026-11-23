from rest_framework.settings import api_settings
from tables.exceptions import BulkSaveValidationError

# DRF's key for a problem of a whole item or section rather than one of its fields.
NON_FIELD_ERRORS_KEY = api_settings.NON_FIELD_ERRORS_KEY


def _as_field_detail(problems) -> dict:
    """Return `problems` as one DRF-style detail keyed by field.

    A problem is a DRF detail dict (`serializer.errors`), a message, or a list mixing
    both; a bare message belongs to the item as a whole.
    """
    if isinstance(problems, dict):
        return dict(problems)
    if isinstance(problems, str):
        return {NON_FIELD_ERRORS_KEY: [problems]}
    detail: dict = {}
    for problem in problems:
        _merge(detail, _as_field_detail(problem))
    return detail


def _merge(target: dict, detail: dict) -> None:
    for key, value in detail.items():
        existing = target.get(key)
        if existing is None:
            target[key] = value
        elif isinstance(existing, dict) and isinstance(value, dict):
            merged = dict(existing)
            _merge(merged, value)
            target[key] = merged
        else:
            target[key] = _as_list(existing) + _as_list(value)


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


class BulkSaveErrors:
    """The problems of one bulk save, in the shape `BulkSaveValidationError` carries.

    A node or edge's problems are keyed by its list and its position in the payload,
    `{"llm_node_list": {"3": {"prompt_configs": ...}}}`, so the error answer names
    each one as `llm_node_list.3.prompt_configs.1.result_variable`. A problem of a
    whole list, such as an unknown id in `deleted`, is keyed by the list alone.
    """

    def __init__(self):
        self._detail: dict[str, dict] = {}

    def __bool__(self) -> bool:
        return bool(self._detail)

    def add_item(self, section: str, index: int, problems) -> None:
        """Record the problems of the item at `index` of `section`, merged with any it has."""
        items = self._detail.setdefault(section, {})
        _merge(items, {str(index): _as_field_detail(problems)})

    def add_section(self, section: str, messages: list[str]) -> None:
        """Record problems of `section` as a whole."""
        _merge(self._detail.setdefault(section, {}), {NON_FIELD_ERRORS_KEY: list(messages)})

    def as_exception(self) -> BulkSaveValidationError:
        return BulkSaveValidationError(self._detail)

    def raise_if_any(self) -> None:
        """Raise `BulkSaveValidationError` with every recorded problem, if there is one."""
        if self._detail:
            raise self.as_exception()
