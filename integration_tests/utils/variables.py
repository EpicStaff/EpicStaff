import os

# DJANGO_URL = "http://django_app:8000/api"
# MANAGER_URL = "http://manager:8000"
rhost = '127.0.0.1'

DJANGO_URL = os.environ.get('DJANGO_URL', 'http://127.0.0.1:8000/api')
MANAGER_URL = os.environ.get('MANAGER_URL', "http://127.0.0.1:8001")