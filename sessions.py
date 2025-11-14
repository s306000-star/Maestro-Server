# -*- coding: utf-8 -*-
"""
sessions.py — إدارة جلسات تيليجرام المخزنة في MongoDB بدل الملفات
"""

from flask import Blueprint, jsonify, request, current_app
from pyrogram import Client
import asyncio

sessions_bp = Blueprint("sessions", __name__)


# ============================================================
# 🔧 دوال MongoDB
# ============================================================

def get_all_sessions():
    """جلب كل الحسابات من MongoDB"""
    col = current_app.sessions_collection
    return list(col.find({}, {"_id": 0}))

def get_session(phone):
    """جلب جلسة محددة من MongoDB"""
    col = current_app.sessions_collection
    doc = col.find_one({"phone": phone})
    return doc

def delete_session(phone):
    """حذف حساب من MongoDB"""
    col = current_app.sessions_collection
    col.delete_one({"phone": phone})


# ============================================================
# 📌 API: جلب جميع الحسابات
# ============================================================

@sessions_bp.route("/sessions/all", methods=["GET"])
def sessions_all():
    data = get_all_sessions()
    return jsonify({"ok": True, "accounts": data})


# ============================================================
# 📌 API: اختبار اتصال حساب معين
# ============================================================

@sessions_bp.route("/sessions/test", methods=["POST"])
def test_session():
    """
    يستقبل:
    {
        "phone": "+966500000000"
    }
    """
    data = request.json
    phone = data.get("phone")

    if not phone:
        return jsonify({"ok": False, "error": "Missing phone"}), 400

    acc = get_session(phone)
    if not acc:
        return jsonify({"ok": False, "error": "Account not found"}), 404

    session_string = acc.get("session")
    api_id = acc.get("api_id")
    api_hash = acc.get("api_hash")

    # إنشاء event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        async def check():
            client = Client(
                name=phone,
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string
            )

            await client.connect()
            ok = await client.is_authorized()
            await client.disconnect()
            return ok

        authorized = loop.run_until_complete(check())

        return jsonify({"ok": True, "authorized": authorized})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# 📌 API: حذف حساب
# ============================================================

@sessions_bp.route("/sessions/delete", methods=["POST"])
def delete_acc():
    data = request.json
    phone = data.get("phone")

    if not phone:
        return jsonify({"ok": False, "error": "Missing phone"}), 400

    delete_session(phone)
    return jsonify({"ok": True, "message": "Account deleted"})


# ============================================================
# 📌 API: عدد الحسابات
# ============================================================

@sessions_bp.route("/sessions/count", methods=["GET"])
def count_sessions():
    count = len(get_all_sessions())
    return jsonify({"ok": True, "count": count})
