"""Re-entering the values of an installed plugin's secret slots."""

from django.db import IntegrityError, transaction
from tables.import_export.enums import EntityType
from tables.models import Secret
from tables.services.secrets.secret_service import secret_service

from plugins.exceptions import InvalidPluginSecretsError
from plugins.manifest import slot_secret_name
from plugins.models import Plugin, PluginResource
from plugins.resource_types import IMPORTED_ENTITIES, RESOURCE_MODELS, PluginResourceType
from plugins.services.install_checks import check_secret_values

_SECRET_NAME_MAX = Secret._meta.get_field("name").max_length


class PluginSecretSlotService:
    """Replace slot values with fresh secrets, never by rewriting a stored value.

    A Secret's value is never updated in place anywhere in EpicStaff, so a new
    value is a new Secret under the old name, bound everywhere the old one was.
    """

    def replace(self, plugin: Plugin, values: dict[str, str], *, user) -> None:
        """Give each named slot a fresh secret holding its new value, all or nothing.

        A slot whose secret still exists keeps every binding of it, the org's own
        included. A slot whose secret was deleted gets a new one bound as the
        plugin file binds it, to the plugin's rows that still exist.

        Raises:
            InvalidPluginSecretsError: an unknown, blank or over-long value, no
                value at all, or the slot's secret name is now taken by another
                secret of the org.
        """
        declared = [slot["name"] for slot in plugin.secret_slots]
        check_secret_values(declared, values, require_every_slot=False)
        with transaction.atomic():
            for slot in declared:
                if slot in values:
                    self._replace_slot(plugin, slot, values[slot], user)

    def _replace_slot(self, plugin: Plugin, slot: str, value: str, user) -> None:
        link = PluginResource.objects.filter(
            plugin=plugin, resource_type=PluginResourceType.SECRET, manifest_ref=slot
        ).first()
        old = (
            Secret.objects.select_for_update()
            .filter(pk=link.object_id, org_id=plugin.org_id)
            .first()
            if link is not None
            else None
        )
        if old is not None:
            name = old.name
            # Frees the unique (org, name) for the new secret; the row is deleted below.
            old.name = f"{name}__replaced_{old.pk}"[:_SECRET_NAME_MAX]
            old.save(update_fields=["name"])
        else:
            name = slot_secret_name(plugin.plugin_id, slot)

        new = self._create(plugin, slot, name, value, user)
        if old is not None:
            _move_references(old, new)
            old.delete()
        else:
            self._bind_as_the_file_does(plugin, slot, new)

        if link is None:
            PluginResource.objects.create(
                plugin=plugin,
                resource_type=PluginResourceType.SECRET,
                object_id=new.pk,
                manifest_ref=slot,
            )
        else:
            link.object_id = new.pk
            link.save(update_fields=["object_id"])

    def _create(self, plugin: Plugin, slot: str, name: str, value: str, user) -> Secret:
        try:
            # A savepoint, so a taken name surfaces as a slot error, not a broken transaction.
            with transaction.atomic():
                return secret_service.create(
                    text=value, name=name, org_id=plugin.org_id, created_by=user
                )
        except IntegrityError as exc:
            raise InvalidPluginSecretsError(
                [
                    {
                        "slot": slot,
                        "message": f"A secret named '{name}' already exists. "
                        "Rename or delete it, then enter the value again.",
                    }
                ]
            ) from exc

    def _bind_as_the_file_does(self, plugin: Plugin, slot: str, secret: Secret) -> None:
        bindings = [
            binding
            for binding in plugin.manifest.get("secret_bindings", [])
            if binding["slot"] == slot
        ]
        for binding in bindings:
            resource_type = IMPORTED_ENTITIES[EntityType(binding["entity"])].resource_type
            object_ids = PluginResource.objects.filter(
                plugin=plugin, resource_type=resource_type, manifest_ref=str(binding["ref"])
            ).values_list("object_id", flat=True)
            resource_model = RESOURCE_MODELS[resource_type]
            resource_model.model.objects.filter(
                pk__in=object_ids, **{resource_model.org_field: plugin.org_id}
            ).update(**{binding["field"]: secret})


def _move_references(old: Secret, new: Secret) -> None:
    """Point every foreign key and many-to-many link at `old` to `new` instead."""
    for relation in Secret._meta.related_objects:
        if relation.many_to_many:
            through = relation.through
            [link_field] = [
                field for field in through._meta.fields if field.related_model is Secret
            ]
            through.objects.filter(**{link_field.name: old}).update(**{link_field.name: new})
        else:
            relation.related_model._base_manager.filter(**{relation.field.name: old}).update(
                **{relation.field.name: new}
            )
