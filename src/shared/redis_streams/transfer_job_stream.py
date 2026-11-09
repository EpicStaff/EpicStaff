"""Contract of the streams carrying transfer-job work to django_app.

django_app adds one entry per export or import job once the job is committed, to
the stream of the job's lane: heavy jobs (flows, knowledge collections, sessions)
on `TRANSFER_JOB_STREAM`, light ones (tools, presets, single nodes) on
`TRANSFER_JOB_LIGHT_STREAM`, so a small export never waits behind a large one.
manager adds one sweep request on its schedule, to the heavy stream only. django_app
reads each stream through its own consumer group, so each entry is handled by
exactly one container.
"""

TRANSFER_JOB_STREAM = "transfer_jobs.requests"
TRANSFER_JOB_CONSUMER_GROUP = "django-transfer-jobs"
TRANSFER_JOB_LIGHT_STREAM = "transfer_jobs.light_requests"
TRANSFER_JOB_LIGHT_CONSUMER_GROUP = "django-transfer-jobs-light"
# An entry holds one of these two fields: a job to run, or a sweep to do.
TRANSFER_JOB_ID_FIELD = "job_id"
TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD = "sweep_requested_at"

# Approximate cap on each stream's length: entries that were never consumed cannot pile up.
TRANSFER_JOB_STREAM_MAXLEN = 10000
