"""The OpenAPI schema has to render as YAML, not only as JSON.

`/api/schema/` serves YAML unless the client asks for JSON. drf-spectacular's YAML
renderer uses a SafeDumper that represents only exact built-in types, so a `StrEnum`
member left in a hand-written `extend_schema` example (as a key or a value) passes
the JSON renderer and Swagger UI, but turns the default schema response into a 500.
"""

import pytest
import yaml
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.renderers import OpenApiYamlRenderer

# Nothing here touches the database, but tests/conftest.py's session-scoped
# `flush_test_db_once` would otherwise target the real dev database.
pytestmark = pytest.mark.django_db


def test_generated_schema_renders_as_yaml():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    rendered = OpenApiYamlRenderer().render(schema)

    assert yaml.safe_load(rendered)["paths"]
