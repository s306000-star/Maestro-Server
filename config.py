# -*- coding: utf-8 -*-
"""
config.py — Telegram Maestro Backend (MongoDB Edition)
تهيئة النظام بعد استبدال تخزين الملفات بـ MongoDB بالكامل
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# 📦 تحميل ملف .env إذا وُجد (ليس مطلوبًا في Render)
# ============================================================
BASE_DIR = Path(os.getcwd())
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

# ============================================================
# 🌐 إعدادات عامة للسيرفر
# ============================================================
CONFIG = {
    "HOST": os.getenv("HOST", "0.0.0.0"),
    "PORT": int(os.getenv("PORT", 5000)),
    "DEBUG": os.getenv("DEBUG", "false").lower() == "true",
    "ENV": os.getenv("ENV", "development"),
    "SECRET_KEY": os.getenv("SECRET_KEY", "default-secret-key"),

    # لم نعد نستخدم الجلسات على الملفات نهائياً
    "UPLOADS_FOLDER": str(BASE_DIR / "uploads"),
    "HISTORY_FOLDER": str(BASE_DIR / "history"),
}

# ============================================================
# 🤖 بيانات Telegram API (اختياري)
# ============================================================
try:
    API_ID = int(os.getenv("API_ID", "0"))
except:
    API_ID = 0

API_HASH = os.getenv("API_HASH", "")


# ============================================================
# 🧩 طباعة ملخص الإعدادات (Debug Mode)
# ============================================================
def print_config_summary():
    if CONFIG["DEBUG"]:
        print("\n🧩 Telegram Maestro Config Summary:")
        print(f"├ Host: {CONFIG['HOST']}:{CONFIG['PORT']}")
        print(f"├ Debug Mode: {CONFIG['DEBUG']}")
        print(f"├ Environment: {CONFIG['ENV']}")
        print(f"├ API ID Loaded: {'✔️' if API_ID else '❌'}")
        print(f"└ Uploads Folder: {CONFIG['UPLOADS_FOLDER']}\n")


if __name__ == "__main__":
    print_config_summary()
