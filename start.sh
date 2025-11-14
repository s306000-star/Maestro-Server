#!/bin/bash

echo "🔄 Synchronizing Telegram sessions from GitHub..."
python3 sessions_syncy.py

echo "🚀 Starting Maestro server..."
gunicorn app:app --bind 0.0.0.0:$PORT --worker-class gevent --workers 1
