#!/bin/bash
set -e

echo "startup.sh running"
echo "Starting gunicorn..."

exec gunicorn --bind 0.0.0.0:${PORT:-8000} --timeout 600 app:app
