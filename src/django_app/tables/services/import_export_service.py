import json

from django.http import HttpResponse
from django.core.exceptions import ValidationError

from tables.utils.helpers import generate_file_name
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.registry import entity_registry
from tables.import_export.constants import MAIN_ENTITY_KEY


class ViewSetImportExportService:
    def __init__(
        self, entity_type, export_prefix, filename_attr, response_serializer_class
    ):
        self.entity_type = entity_type
        self.export_prefix = export_prefix
        self.filename_attr = filename_attr
        self.response_serializer_class = response_serializer_class
        self.export_service = ExportService(entity_registry)
        self.import_service = ImportService(entity_registry)

    def export_entity(self, instance):
        data = self.export_service.export_entities(self.entity_type, [instance.pk])
        json_data = json.dumps(data, indent=4)

        base_name = getattr(instance, self.filename_attr, "object")
        filename = generate_file_name(base_name, prefix=self.export_prefix)

        response = HttpResponse(json_data, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def bulk_export(self, entity_ids):
        data = self.export_service.export_entities(self.entity_type, entity_ids)
        json_data = json.dumps(data, indent=4)

        filename = generate_file_name(
            f"{self.export_prefix}_bulk_{len(entity_ids)}", prefix=self.export_prefix
        )

        response = HttpResponse(json_data, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def import_entity(self, file, model_class):
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON file")

        main_entity = data[MAIN_ENTITY_KEY]
        if main_entity != self.entity_type:
            raise ValidationError(
                f"Provided wrong entity. Got: {main_entity}. Expected: {self.entity_type}"
            )

        id_mapper = self.import_service.import_data(data, self.entity_type)
        new_id = id_mapper.get_new_ids(self.entity_type)[0]
        instance = model_class.objects.get(id=new_id)

        return self.response_serializer_class(instance).data
