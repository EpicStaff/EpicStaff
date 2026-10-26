import importlib


def test_rest_controllers_import():
    # Controllers resolve their schema annotations at import time; a missing
    # export in the schemas package only shows up when the service starts.
    importlib.import_module("presentation.rest.controllers.rag")
