#!/bin/sh
set -e

# No migrations and no server here: the worker owns no database and listens on no port.
# It only needs the manager, which compose starts (and health-checks) first.
exec python -m worker.main
