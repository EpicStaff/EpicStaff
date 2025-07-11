from rest_framework.renderers import BaseRenderer


class SSERenderer(BaseRenderer):
    """
    Renderer which simply returns data as-is for streaming, with the proper content type.
    """

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None  # Typically, SSE data is transmitted as raw text

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # We assume 'data' is already a string (or bytes)
        return data
