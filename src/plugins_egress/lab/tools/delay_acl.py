#!/usr/bin/env python3
"""Lab only: an external ACL that answers OK, three seconds late for names under .slow.rebind.test.

It takes Squid's lines in either shape the lab uses, `<host> -` or `<user> <host> -` (the
production helper's `%ul %DST`): the host is the field before the trailing `-`.

The race instance's configuration checks it after the access rules, between the private-address
check and the connection, so that a 1 s DNS answer expires in between, as an attacker would time
it. It never ships.
"""

import sys
import time

SLOW_SUFFIX = ".slow.rebind.test"

for line in sys.stdin:
    fields = line.split()
    if fields and fields[-1] == "-":
        fields = fields[:-1]
    if fields and fields[-1].lower().rstrip(".").endswith(SLOW_SUFFIX):
        time.sleep(3)
    sys.stdout.write("OK\n")
    sys.stdout.flush()
