# plugins_egress: Squid for plugin backends' outbound HTTPS, behind a start-up firewall against
# private destinations. Build context: src/plugins_egress (see docker-compose.yaml).
FROM alpine:3.23@sha256:85fe1e81d6758c208f3e1eed4338a1997e19d4be002d4dd32d3100c9a8c010a0

# Any 7.6 revision: Alpine drops a superseded revision from its mirrors, so an exact one would
# stop building at the next security rebuild. python3 runs the host helper; iptables, ip6tables
# and setpriv serve the entrypoint. Squid's own error pages stay for every answer but the four
# refusals in errors/.
RUN apk add --no-cache squid~7.6 python3 iptables ip6tables setpriv \
    && install -d -m 0755 /etc/squid/errors /etc/squid/policy \
    && cp /usr/share/squid/errors/templates/* /etc/squid/errors/ \
    && squid -v | head -n 1

COPY errors/ /etc/squid/errors/
COPY squid.conf private_ranges.txt /etc/squid/
COPY --chmod=0755 plugin_host_acl.py /usr/local/bin/plugin_host_acl
COPY --chmod=0755 entrypoint.sh /usr/local/bin/plugins-egress-entrypoint

EXPOSE 3128
ENTRYPOINT ["/usr/local/bin/plugins-egress-entrypoint"]
