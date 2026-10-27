#!/usr/bin/env python3
"""Lab only: Squid's basic_ncsa_auth, made slow, so one checker is easy to overload.

Run as `slow_auth <passwords file>`: it starts the real helper on the same file and passes each
line on after 0.2 s, answer for answer. The overload instances use it; it never ships.
"""

import subprocess
import sys
import time

checker = subprocess.Popen(
    ["/usr/lib/squid/basic_ncsa_auth", sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE
)
for line in sys.stdin.buffer:
    time.sleep(0.2)
    checker.stdin.write(line)
    checker.stdin.flush()
    sys.stdout.buffer.write(checker.stdout.readline())
    sys.stdout.flush()
