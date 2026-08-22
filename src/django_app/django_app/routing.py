from django.urls import re_path

from tables.graph_collab.consumers import GraphEditConsumer

websocket_urlpatterns = [
    re_path(r"ws/graphs/(?P<graph_id>\d+)/edit/$", GraphEditConsumer.as_asgi()),
]
