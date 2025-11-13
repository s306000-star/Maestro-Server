# -*- coding: utf-8 -*-
"""
utils.py - دوال مساعدة عامة للمشروع
"""

import asyncio
import os
from flask import jsonify
import logging
import json
from datetime import datetime

# إعداد نظام التسجيل (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MaestroBackend")


def format_response(success=True, data=None, error=None, code=200):
    """
    تنسيق استجابة JSON بشكل موحد.
    """
    response = {
        "ok": success,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if data is not None:
        response["data"] = data
    if error:
        response["error"] = str(error)
        
    # For client-side compatibility, ensure a `data` key exists on errors too
    if not success and "data" not in response:
        response["data"] = {}
        
    return jsonify(response), code

def ensure_event_loop():
    """
    التأكد من وجود حلقة أحداث (event loop) نشطة في الـ thread الحالي.
    """
    try:
        loop = asyncio.get_running_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:  # 'RuntimeError: There is no current event loop...'
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

def run_in_new_loop(coro):
    """
    تشغيل coroutine في حلقة أحداث جديدة وموثوقة وإرجاع النتيجة.
    """
    loop = ensure_event_loop()
    return loop.run_until_complete(coro)

def ensure_folder(path: str):
    """تأكد من وجود المجلد، وإذا لم يكن موجودًا أنشئه."""
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        logging.error(f"⚠️ Error creating folder {path}: {e}")

def read_json_safe(file_path):
    """
    قراءة ملف JSON بأمان.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def write_json_safe(file_path, data):
    """
    كتابة ملف JSON بأمان.
    """
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"write_json_safe failed for {file_path}: {e}")
        return False

