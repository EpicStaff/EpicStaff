#!/bin/sh
set -e

python -m app.index_setup.runner

exec python run.py