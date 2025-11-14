# -*- coding: utf-8 -*-
"""
auth.py — تسجيل الدخول لحساب تيليجرام مع تخزين الجلسات في MongoDB
"""

from flask import Blueprint, request, jsonify, current_app
from pyrogram import Client
import asyncio

auth_bp = Blueprint("auth", __name__)


# ============================================================
# 🔧 دوال مساعدة
# ============================================================

async def send_login_code(phone, api_id, api_hash):
    """إرسال كود تسجيل الدخول إلى رقم الهاتف"""
    try:
        client = Client(
            name=f"login_{phone}",
            api_id=api_id,
            api_hash=api_hash
        )
        await client.connect()
        sent = await client.send_code(phone)
        await client.disconnect()
        return sent.phone_code_hash, None

    except Exception as e:
        return None, str(e)


async def verify_login_code(phone, api_id, api_hash, phone_code_hash, code):
    """التحقق من كود تسجيل الدخول وتوليد Session String"""
    try:
        client = Client(
            name=f"login_{phone}",
            api_id=api_id,
            api_hash=api_hash
        )
        await client.connect()

        # تسجيل الدخول
        await client.sign_in(
            phone=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code
        )

        # استخراج Session String
        session_string = await client.export_session_string()

        await client.disconnect()
        return session_string, None

    except Exception as e:
        return None, str(e)


# ============================================================
# 📌 API: طلب إرسال الكود
# ============================================================

@auth_bp.route("/auth/send_code", methods=["POST"])
def send_code():
    """
    يستقبل:
    {
        "phone": "+966500000000",
        "api_id": 12345,
        "api_hash": "xxxxxx"
    }
    ويرجع phone_code_hash
    """
    data = request.json

    phone = data.get("phone")
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")

    if not phone or not api_id or not api_hash:
        return jsonify({"ok": False, "error": "Missing fields"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    phone_code_hash, err = loop.run_until_complete(
        send_login_code(phone, api_id, api_hash)
    )

    if err:
        return jsonify({"ok": False, "error": err}), 500

    return jsonify({
        "ok": True,
        "phone": phone,
        "phone_code_hash": phone_code_hash
    })


# ============================================================
# 📌 API: التحقق من الكود وتسجيل الدخول
# ============================================================

@auth_bp.route("/auth/verify", methods=["POST"])
def verify():
    """
    يستقبل:
    {
        "phone": "+966500000000",
        "api_id": 12345,
        "api_hash": "xxxxxx",
        "phone_code_hash": "xxxxx",
        "code": "12345"
    }
    """

    data = request.json

    phone = data.get("phone")
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    phone_code_hash = data.get("phone_code_hash")
    code = data.get("code")

    if not all([phone, api_id, api_hash, phone_code_hash, code]):
        return jsonify({"ok": False, "error": "Missing fields"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    session_string, err = loop.run_until_complete(
        verify_login_code(phone, api_id, api_hash, phone_code_hash, code)
    )

    if err:
        return jsonify({"ok": False, "error": err}), 500

    # ========================================================
    # 🗄 تخزين الجلسة في MongoDB
    # ========================================================
    sessions = current_app.sessions_collection

    sessions.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "api_id": api_id,
            "api_hash": api_hash,
            "session": session_string
        }},
        upsert=True
    )

    return jsonify({
        "ok": True,
        "message": "Account saved successfully",
        "session_saved": True
    })


# ============================================================
# 📌 API: حذف حساب
# ============================================================

@auth_bp.route("/auth/delete", methods=["POST"])
def delete_account():
    data = request.json
    phone = data.get("phone")

    if not phone:
        return jsonify({"ok": False, "error": "Missing phone"}), 400

    sessions = current_app.sessions_collection
    sessions.delete_one({"phone": phone})

    return jsonify({"ok": True, "message": "Account deleted"})


# ============================================================
# 📌 API: جلب جميع الحسابات المسجلة
# ============================================================

@auth_bp.route("/auth/accounts", methods=["GET"])
def get_accounts():
    sessions = current_app.sessions_collection
    data = list(sessions.find({}, {"_id": 0}))

    return jsonify({"ok": True, "accounts": data})
