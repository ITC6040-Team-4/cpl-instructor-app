#!/bin/bash
set -e
echo "startup.sh running"
ls -la
echo "Starting gunicorn now"
exec gunicorn --bind=0.0.0.0:${PORT:-8000} --timeout 600 app:app
