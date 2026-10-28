"""
Passenger entry point for cPanel "Setup Python App".

cPanel expects a ``passenger_wsgi.py`` in the application root. Adjust the two
values below to match the paths shown in cPanel » Setup Python App:

  * APPLICATION_ROOT  – directory containing manage.py
  * PYTHON_INTERPRETER – .../virtualenv/<app>/<version>/bin/python

Then restart the application from cPanel.
"""

import os
import sys

APPLICATION_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON_INTERPRETER = os.environ.get(
    "MAILGEN_PYTHON",
    "/home/USER/virtualenv/app.example.com/3.11/bin/python",
)

# Secrets live outside the document root in production.
os.environ.setdefault("MAILGEN_ENV_FILE", "/home/USER/.mailgen/env")

if APPLICATION_ROOT not in sys.path:
    sys.path.insert(0, APPLICATION_ROOT)

# Re-exec under the virtualenv interpreter when Passenger starts with the
# system Python. Skipped automatically if the path does not exist.
if sys.executable != PYTHON_INTERPRETER and os.path.exists(PYTHON_INTERPRETER):
    os.execl(PYTHON_INTERPRETER, PYTHON_INTERPRETER, *sys.argv)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailgen.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
