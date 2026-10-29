# The egress lab's helper image: the policy writer stand-in, the plugin clients, the lab DNS server
# and the victim. Python 3.12.10 and bcrypt and loguru as in the plugin node, whose
# EgressPolicyWriter the stand-in runs. Lab only; the proxy runs the product image.
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
RUN pip install --no-cache-dir bcrypt==5.0.0 loguru==0.7.3 httpx==0.28.1 requests==2.34.2 dnslib==0.9.26
