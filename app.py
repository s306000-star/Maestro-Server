# -*- coding: utf-8 -*-
"""
app.py — Telegram Maestro Backend (MongoDB Edition)
إصدار احترافي متكامل بعد تحويل المشروع إلى تخزين الجلسات داخل MongoDB بدون ملفات.
"""

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import logging
from importlib import import_module
from config import CONFIG
from utils import ensure_folder, ensure_event_loop
from pymongo import MongoClient
import os

# ============================================================
# 🔧 إنشاء التطبيق + CORS
# ============================================================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ============================================================
# 🧾 نظام التسجيل (Logging)
# ============================================================
LOG_FILE = "server.log"
log_format = "%(asctime)s [%(levelname)s] (%(name)s): %(message)s"

logging.basicConfig(
    level=logging.DEBUG if CONFIG["DEBUG"] else logging.INFO,
    format=log_format,
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger("TelegramMaestro")

logger.info("🚀 Initializing Telegram Maestro Backend...")

# ============================================================
# 🗄 الاتصال بـ MongoDB
# ============================================================
try:
    MONGO_URL = os.getenv("MONGO_URL")
    mongo_client = MongoClient(MONGO_URL)

    mongo_db = mongo_client["maestro_sessions_db"]
    sessions_collection = mongo_db["sessions"]

    # تخزين الاتصال داخل Flask app
    app.mongo_db = mongo_db
    app.sessions_collection = sessions_collection

    logger.info("🟢 Connected successfully to MongoDB!")
except Exception as e:
    logger.error(f"❌ MongoDB Connection Error: {e}", exc_info=True)

# ============================================================
# 📁 تجهيز مجلدات المشروع (إن وجدت)
# ============================================================
for key, path in CONFIG.items():
    if key.endswith("_FOLDER"):
        ensure_folder(path)
        logger.info(f"📁 Ensured folder exists: {path}")

# ============================================================
# 🔌 تحميل وربط الـ Blueprints تلقائيًا
# ============================================================
modules = [
    "auth",
    "sessions",
    "sgroups",
    "publish",
    "filters",
    "smart_safe_join"   # ← مهم جدًا
]

for module_name in modules:
    try:
        mod = import_module(module_name)
        bp = getattr(mod, f"{module_name}_bp")  # ← يبحث عن smart_safe_join_bp
        app.register_blueprint(bp, url_prefix="/api")
        logger.info(f"✅ Registered module: {module_name}")
    except Exception as e:
        logger.error(f"❌ Failed to load module '{module_name}': {e}", exc_info=True)

# ============================================================
# 🏠 الصفحة الرئيسية
# ============================================================
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "ok": True,
        "service": "Telegram Maestro Backend",
        "version": "2.0",
        "status": "running",
        "mongo": "connected",
        "modules": modules
    }), 200

# ============================================================
# ✨ Favicon
# ============================================================
@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

# ============================================================
# 🔍 Check status
# ============================================================
@app.route("/status")
def status():
    return jsonify({"ok": True, "status": "running"}), 200

# ============================================================
# ⚠️ Global Error Handler
# ============================================================
@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled Exception:", exc_info=True)
    from utils import format_response
    return format_response(False, str(e), {"msg": "Internal server error"}, 500)

# ============================================================
# 🚀 Run server (Local Only) — Render ignores this
# ============================================================
if __name__ == "__main__":
    ensure_event_loop()
    app.run(host=CONFIG["HOST"], port=CONFIG["PORT"])
