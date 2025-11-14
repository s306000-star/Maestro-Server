# -*- coding: utf-8 -*-
"""
app.py — Telegram Maestro Backend
إصدار نهائي محسّن ومنظم بنمط إنتاجي احترافي.
"""

from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import logging
from importlib import import_module
from config import CONFIG
from utils import ensure_folder, ensure_event_loop

# ============================================================
# 🧱 إنشاء التطبيق وتفعيل CORS
# ============================================================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ============================================================
# 🧾 نظام التسجيل الاحترافي (Logging)
# ============================================================
LOG_FILE = "server.log"
log_format = "%(asctime)s [%(levelname)s] (%(name)s): %(message)s"

logging.basicConfig(
    level=logging.DEBUG if CONFIG["DEBUG"] else logging.INFO,
    format=log_format,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TelegramMaestro")

logger.info("🚀 Telegram Maestro Backend initializing...")

# --- إنشاء المجلدات إذا لم تكن موجودة ---
for key, path in CONFIG.items():
    if key.endswith('_FOLDER'):
        ensure_folder(path)
        logger.info(f"Ensured folder exists: {path}")

# ============================================================
# 🔗 تحميل وربط الـ Blueprints تلقائيًا
# ============================================================
# القائمة المعدّلة بشكل صحيح 🔥
modules = ["auth", "sessions", "sgroups", "publish", "filters", "smart_safe_join"]

for module_name in modules:
    try:
        mod = import_module(module_name)
        bp = getattr(mod, f"{module_name}_bp")
        app.register_blueprint(bp, url_prefix="/api")
        logger.info(f"✅ Registered module: {module_name}")
    except Exception as e:
        logger.error(
            f"❌ Failed to register module '{module_name}': {e}",
            exc_info=True
        )

# ============================================================
# 🏠 الصفحة الرئيسية (Index)
# ============================================================
@app.route("/", methods=["GET"])
def index():
    """عرض الحالة العامة للتطبيق."""
    return jsonify({
        "ok": True,
        "service": "Telegram Maestro Backend",
        "version": "2.0",
        "status": "running",
        "debug": CONFIG["DEBUG"],
        "available_modules": modules,
        "usage": {
            "status": "/api/status",
            "sessions": "/api/get-active-accounts",
            "scan_channels": "/api/scan-channels",
            "scan_groups": "/api/scan-groups"
        }
    }), 200

# ============================================================
# ✨ معالجة طلب أيقونة الموقع (Favicon)
# ============================================================
@app.route('/favicon.ico')
def favicon():
    return Response(status=204)

# ============================================================
# 🩺 فحص حالة السيرفر
# ============================================================
@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "ok": True,
        "status": "running",
        "version": "2.0",
        "debug": CONFIG["DEBUG"],
        "environment": CONFIG["ENV"]
    }), 200

# ============================================================
# 🚨 معالجة الأخطاء العامة (Global Error Handler)
# ============================================================
@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled Exception: %s", e)
    from utils import format_response
    return format_response(
        success=False,
        error=str(e),
        data={"message": "Internal server error. Check logs for details."},
        code=500
    )

# ============================================================
# 🚀 بدء تشغيل الخادم
# ============================================================
if __name__ == "__main__":
    ensure_event_loop()
    app.run(
        host=CONFIG["HOST"],
        port=CONFIG["PORT"]
    )
