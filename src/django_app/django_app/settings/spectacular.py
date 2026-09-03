SPECTACULAR_SETTINGS = {
    "TITLE": "EpicStaff API",
    "VERSION": "v1",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
    },
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "django_app.spectacular_hooks.assign_tags_postprocessing_hook",
        "django_app.spectacular_hooks.add_org_header_postprocessing_hook",
    ],
}