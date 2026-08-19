import os

from celery import Celery


# Tell Celery which Django settings module to use
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.base",
)


app = Celery("amfi_project")


# Read CELERY_* settings from Django settings.py
app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)


# Automatically discover tasks.py inside installed Django apps
app.autodiscover_tasks()