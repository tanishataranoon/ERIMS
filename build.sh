#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py setup_roles

# Optional: load demo data on Render (set SEED_DEMO_DATA=true in the Render dashboard).
# Safe to leave on: seed_data skips stock if it already exists.
if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  python manage.py seed_data --with-users --password "${DEMO_PASSWORD:-Erims@2026}"
fi
