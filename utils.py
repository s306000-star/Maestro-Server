# -*- coding: utf-8 -*-
"""
utils.py — دوال مساعدة بعد التحويل الكامل إلى MongoDB
"""

import asyncio
import os
import logging
from flask import jsonify
from datetime import datetime

# تهيئة نظام التسجيل Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MaestroBackend")


# ============================================================
# 🔄 رد JSON موحّد
# ============================================================
def format_response(success=True, data=None, error=None, code=200):
    response = {
        "ok": success,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data or {}
    }
    if error:
        response["error"] = str(error)
    return jsonify(response), code


# ============================================================
# 🔁 Loop Manager (مهم لـ Pyrogram)
# ============================================================
def ensure_event_loop():
    try:
        loop = asyncio.get_running_loop()
        if loop.is_closed():
            raise RuntimeError("Loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def run_in_new_loop(coro):
    loop = ensure_event_loop()
    return loop.run_until_complete(coro)


# ============================================================
# 📁 إنشاء مجلدات (لرفع ملفات فقط)
# ============================================================
def ensure_folder(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        logger.error(f"Error creating folder {path}: {e}")
