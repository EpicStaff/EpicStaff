import pkgutil
from importlib import import_module
from importlib.util import find_spec

from django.db import models
from rbac.models import OrgScopedModel


class AbstractBinding(OrgScopedModel):
    resource_id = models.CharField(max_length=255)
    # The proxied resource carries no creation date; the binding is created
    # together with it, so this timestamp is the resource's effective age.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


def _autodiscover_binding_models() -> None:
    """Import every `proxies.<service>.models` so Django registers the bindings."""
    proxies_package = import_module(__package__)
    for module_info in pkgutil.iter_modules(proxies_package.__path__):
        if not module_info.ispkg or module_info.name == "migrations":
            continue
        models_module = f"{__package__}.{module_info.name}.models"
        if find_spec(models_module) is not None:
            import_module(models_module)


_autodiscover_binding_models()
