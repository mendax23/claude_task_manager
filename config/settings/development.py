from .base import *  # noqa: F401, F403

DEBUG = True
SECRET_KEY = "dev-insecure-secret-key-do-not-use-in-production"

# Allow all hosts in development
ALLOWED_HOSTS = ["*"]

# Use console email backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Django Extensions shell_plus settings
SHELL_PLUS = "ipython"
SHELL_PLUS_PRINT_SQL = True

# Disable throttling in development
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

# Celery eager execution option for tests (override per-test if needed)
CELERY_TASK_ALWAYS_EAGER = False
