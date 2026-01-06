#!/bin/bash
cd /opt/ipim/backend
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export POSTGRES_DB=ipam_db
export POSTGRES_USER=ipam_user
export POSTGRES_PASSWORD=ususAcflk7XmBTkovAoa4GT8INznb0A4
export DJANGO_SETTINGS_MODULE=ipam_project.settings
exec python3 manage.py runserver 0.0.0.0:8000
