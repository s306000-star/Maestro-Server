# -*- coding: utf-8 -*-
"""
config.py
🔧 تحميل إعدادات Telegram Maestro Backend من ملف .env
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# 📦 تحميل ملف البيئة .env
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
    "TOKEN_EXPIRE_HOURS": int(os.getenv("TOKEN_EXPIRE_HOURS", 24)),

    # 🧠 إعداد المجلدات الخاصة بالتطبيق باستخدام المسار الأساسي
    "UPLOADS_FOLDER": str(BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads")),
    "SESSIONS_FOLDER": str(BASE_DIR / os.getenv("SESSIONS_FOLDER", "sessions")),
    "HISTORY_FOLDER": str(BASE_DIR / os.getenv("HISTORY_FOLDER", "history")),
}

# ============================================================
# 🤖 بيانات Telegram API
# ============================================================
try:
    API_ID = int(os.getenv("API_ID", "0"))
except ValueError:
    API_ID = 0

API_HASH = os.getenv("API_HASH", "")

# ============================================================
# 📁 تكوين مسارات المجلدات المستخدمة في باقي الملفات
# ============================================================
APP_CONFIG = {
    "UPLOAD_FOLDER": CONFIG["UPLOADS_FOLDER"],
    "SESSIONS_FOLDER": CONFIG["SESSIONS_FOLDER"],
    "HISTORY_FOLDER": CONFIG["HISTORY_FOLDER"],
    "STRING_SESS_DIR": str(BASE_DIR / os.getenv("STRING_SESS_DIR", "string_sessions")),
}

# ============================================================
# 🧩 دالة مساعدة لعرض الإعدادات النشطة (للتصحيح فقط)
# ============================================================
def print_config_summary():
    """يطبع ملخص الإعدادات النشطة في حالة التشغيل Debug"""
    if CONFIG["DEBUG"]:
        print("\n🧩 Telegram Maestro Configuration Summary:")
        print(f"├── Host: {CONFIG['HOST']}:{CONFIG['PORT']}")
        print(f"├── Debug Mode: {CONFIG['DEBUG']}")
        print(f"├── Environment: {CONFIG['ENV']}")
        print(f"├── API_ID Loaded: {'✔️ Yes' if API_ID else '❌ No'}")
        print(f"├── API_HASH Loaded: {'✔️ Yes' if API_HASH else '❌ No'}")
        print(f"├── Sessions Folder: {CONFIG['SESSIONS_FOLDER']}")
        print(f"├── Uploads Folder: {CONFIG['UPLOADS_FOLDER']}")
        print(f"└── History Folder: {CONFIG['HISTORY_FOLDER']}\n")

# ============================================================
# ✅ اختبار التشغيل المستقل
# ============================================================
if __name__ == "__main__":
    print_config_summary()
