from django_app.settings import env

# Baked into the image by CI (Dockerfile.dj build args); empty on a local build.
EPICSTAFF_VERSION = env.str("EPICSTAFF_VERSION", default="")
EPICSTAFF_GIT_REF = env.str("EPICSTAFF_GIT_REF", default="")
EPICSTAFF_GIT_SHA = env.str("EPICSTAFF_GIT_SHA", default="")
EPICSTAFF_COMMIT_DATE = env.str("EPICSTAFF_COMMIT_DATE", default="")
