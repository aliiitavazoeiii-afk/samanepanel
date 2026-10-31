#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# Intentionally omit "seed_base": this is a blank business instance.
python manage.py ensure_admin
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 2 --timeout 60 --access-logfile - --error-logfile -
