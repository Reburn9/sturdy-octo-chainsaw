#!/usr/bin/env bash
set -euo pipefail
python -m pip install -r requirements-postgres.txt
python manage.py collectstatic --noinput
# Free Render services have no separate pre-deploy command. Keep the schema update
# here, before the new instance starts; paid services can move this to pre-deploy.
python manage.py migrate --noinput
python manage.py bootstrap_admin
