#!/usr/bin/env python3
"""Lab only: an external ACL that answers OK, three seconds late for names under .slow.rebind.test.

The race instance's configuration checks it after the access rules, between the private-address
check and the connection, so that a 1 s DNS answer expires in between, as an attacker would time
it. It never ships.
"""

import sys
import time

SLOW_SUFFIX = ".slow.rebind.test"

for line in sys.stdin:
    fields = line.split()
    if fields and fields[0].lower().rstrip(".").endswith(SLOW_SUFFIX):
        time.sleep(3)
    sys.stdout.write("OK\n")
    sys.stdout.flush()
