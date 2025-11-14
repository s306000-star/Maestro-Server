#!/bin/bash
echo "🚀 Starting Maestro server (Safe Mode — No Gunicorn)"
export PYTHONUNBUFFERED=1
python app.py
