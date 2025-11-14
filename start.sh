#!/bin/bash

echo "🚀 Starting Maestro server with MongoDB mode..."
gunicorn app:app --bind 0.0.0.0:$PORT --worker-class gevent --workers 1
