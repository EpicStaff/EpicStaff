from django.db.models.signals import post_delete

from tables.services.python_code_cleanup import OWNER_RELATIONS, delete_python_code


def _owner_field_names_by_model():
    owners: dict[type, list[str]] = {}
    for relation in OWNER_RELATIONS:
        owners.setdefault(relation.related_model, []).append(relation.field.attname)
    return owners


_OWNER_FIELD_NAMES_BY_MODEL = _owner_field_names_by_model()


def _delete_owned_python_code(sender, instance, **kwargs):
    field_names = _OWNER_FIELD_NAMES_BY_MODEL.get(sender)
    if not field_names:
        return
    python_code_ids = {getattr(instance, field_name) for field_name in field_names}
    delete_python_code(python_code_ids, exclude_model=sender)


for owner_model in _OWNER_FIELD_NAMES_BY_MODEL:
    post_delete.connect(
        _delete_owned_python_code,
        sender=owner_model,
        dispatch_uid=f"delete_owned_python_code_{owner_model._meta.label_lower}",
    )
