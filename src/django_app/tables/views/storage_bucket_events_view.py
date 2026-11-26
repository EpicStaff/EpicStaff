import json

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from tables.services.storage_service.bucket_events import (
    BucketEventService,
    changes_from_notification,
)


@csrf_exempt
@require_POST
def storage_bucket_events_view(request: HttpRequest) -> HttpResponse:
    """Receive the storage service's bucket notifications (its webhook target).

    No credentials: the route sits outside the paths epicstaff-nginx proxies to django, so
    only containers on django's own networks reach it, and a record only makes django re-read
    the object it names from the store (see `bucket_events`), so a forged one changes nothing
    the store does not already hold. A plain django view, not a DRF one: it belongs to no
    organization and no API client calls it.

    An error answers 500, and the store sends the notification again later.
    """
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest()
    if not isinstance(payload, dict):
        return HttpResponseBadRequest()
    BucketEventService().apply(changes_from_notification(payload))
    return HttpResponse(status=204)
