# The node lab's helper image: the packer, the stand-in node API (control) and the client
# (tools). Python 3.13 like the probe plugins, with the SDK built from src/plugin_sdk.
# Build context: src/. Lab only; the node itself runs the product image.
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl jq \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.21 aiohttp==3.14.3
COPY ./plugin_sdk/pyproject.toml ./plugin_sdk/uv.lock /opt/plugin_sdk/
COPY ./plugin_sdk/epicstaff_plugin /opt/plugin_sdk/epicstaff_plugin
RUN pip install --no-cache-dir /opt/plugin_sdk
COPY ./es_plugins/lab /lab
WORKDIR /lab
