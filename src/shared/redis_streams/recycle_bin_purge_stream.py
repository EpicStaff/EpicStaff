"""Contract of the stream carrying storage maintenance jobs from manager to django_app.

Manager adds one entry each time a job is due: the daily recycle-bin purge and the hourly
storage measurement. django_app reads the stream through one consumer group, so exactly one
django_app container runs each job. An entry without a job field is a purge, as every entry
was before the measurement was added.
"""

RECYCLE_BIN_PURGE_STREAM = "recycle_bin.purge_requests"
RECYCLE_BIN_PURGE_CONSUMER_GROUP = "django-recycle-bin-purge"
RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD = "requested_at"
RECYCLE_BIN_PURGE_JOB_FIELD = "job"
STORAGE_MEASUREMENT_JOB = "storage_measurement"

# Approximate cap on the stream length: requests that were never consumed cannot pile up.
RECYCLE_BIN_PURGE_STREAM_MAXLEN = 100
