"""Contract of the stream carrying transfer-job work to django_app.

django_app adds one entry per export or import job once the job is committed;
manager adds one sweep request on its schedule. django_app reads the stream
through one consumer group, so each entry is handled by exactly one container.
"""

TRANSFER_JOB_STREAM = "transfer_jobs.requests"
TRANSFER_JOB_CONSUMER_GROUP = "django-transfer-jobs"
# An entry holds one of these two fields: a job to run, or a sweep to do.
TRANSFER_JOB_ID_FIELD = "job_id"
TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD = "sweep_requested_at"

# Approximate cap on the stream length: entries that were never consumed cannot pile up.
TRANSFER_JOB_STREAM_MAXLEN = 10000
