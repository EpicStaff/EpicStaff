"""Lab only: the egress proxy's resolver. Logs every query, serves the lab zones, forwards the rest.

  <x>.rebind.test   A: the first query PUBLIC_ADDRESS, every later one the victim; TTL 1
  <x>.mixed.test    A: PUBLIC_ADDRESS and the victim in one answer; TTL 60
  <x>.private.test  A: the victim; TTL 60
  <x>.ipv6only.test AAAA: a public IPv6 address, and no A record
  anything else     forwarded to Docker's resolver in this container (the host's resolvers)

AAAA for the other lab zones is answered empty, so only their A records matter.
"""

import collections
import socket
import time

from dnslib import AAAA, QTYPE, RR, A, DNSRecord
from dnslib.server import BaseResolver, DNSServer

PUBLIC_ADDRESS = "1.1.1.1"
PUBLIC_IPV6_ADDRESS = "2606:4700:4700::1111"
UPSTREAM = ("127.0.0.11", 53)
LAB_ZONES = (".rebind.test", ".mixed.test", ".private.test", ".ipv6only.test")
rebind_queries: collections.Counter = collections.Counter()


def victim_address() -> str:
    return socket.gethostbyname("victim")


class LabResolver(BaseResolver):
    def resolve(self, request, handler):
        name = str(request.q.qname).rstrip(".").lower()
        query_type = QTYPE[request.q.qtype]
        print(f"{time.time():.3f} query {query_type} {name}", flush=True)
        if not name.endswith(LAB_ZONES):
            try:
                return DNSRecord.parse(request.send(*UPSTREAM, timeout=3))
            except Exception as error:  # A resolver answers SERVFAIL; it never stops.
                print(f"upstream error {type(error).__name__}", flush=True)
                reply = request.reply()
                reply.header.rcode = 2
                return reply
        reply = request.reply()
        if name.endswith(".ipv6only.test"):
            if query_type == "AAAA":
                reply.add_answer(
                    RR(request.q.qname, QTYPE.AAAA, rdata=AAAA(PUBLIC_IPV6_ADDRESS), ttl=60)
                )
            return reply
        if query_type != "A":
            return reply
        if name.endswith(".rebind.test"):
            rebind_queries[name] += 1
            addresses = [PUBLIC_ADDRESS] if rebind_queries[name] == 1 else [victim_address()]
            ttl = 1
        elif name.endswith(".mixed.test"):
            addresses, ttl = [PUBLIC_ADDRESS, victim_address()], 60
        else:
            addresses, ttl = [victim_address()], 60
        for address in addresses:
            reply.add_answer(RR(request.q.qname, QTYPE.A, rdata=A(address), ttl=ttl))
        print(f"{time.time():.3f} answer {name} {addresses} ttl={ttl}", flush=True)
        return reply


if __name__ == "__main__":
    for tcp in (False, True):
        DNSServer(LabResolver(), port=53, address="0.0.0.0", tcp=tcp).start_thread()
    print("labdns ready", flush=True)
    while True:
        time.sleep(3600)
