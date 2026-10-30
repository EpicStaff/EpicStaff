"""Contract of the stream carrying recycle-bin purge requests from manager to django_app.

Manager adds one entry each time the daily purge is due; django_app reads the stream
through one consumer group, so exactly one django_app container runs the purge.
"""

RECYCLE_BIN_PURGE_STREAM = "recycle_bin.purge_requests"
RECYCLE_BIN_PURGE_CONSUMER_GROUP = "django-recycle-bin-purge"
RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD = "requested_at"

# Approximate cap on the stream length: requests that were never consumed cannot pile up.
RECYCLE_BIN_PURGE_STREAM_MAXLEN = 100
