# -*- coding: utf-8 -*-
"""
sgroups.py – Smart Group & Channel Analyzer (MongoDB + Pyrogram Edition)
———————————————————————————————————————————————
✓ يعمل بدون أي ملفات جلسات
✓ يعتمد على Session String المخزنة في MongoDB
✓ فحص المجموعات والقنوات – ينشر رسالة اختبار – يغادر القنوات
"""

from flask import Blueprint, request, jsonify, current_app
from pyrogram import Client, errors
import asyncio

sgroups_bp = Blueprint("sgroups", __name__)


# ======================================================
# 🔧 جلب جلسة الحساب من MongoDB
# ======================================================
def get_account(phone):
    col = current_app.sessions_collection
    acc = col.find_one({"phone": phone})
    return acc


# ======================================================
# 🧩 فحص إرسال رسالة اختبار
# ======================================================
async def test_post_permission(client, chat_id, test_message):
    try:
        await client.send_message(chat_id, test_message)
        return True, "✔️ Can post message"
    except errors.ChatWriteForbidden:
        return False, "⛔ Write forbidden"
    except errors.UserBannedInChannel:
        return False, "⛔ User banned"
    except Exception as e:
        return False, f"❌ {e}"


# ======================================================
# 🧠 تحليل مجموعة / قناة
# ======================================================
async def analyze_dialog(client, dialog, test_message, auto_leave):
    chat = dialog.chat
    chat_id = chat.id
    title = chat.title or "Unknown"

    # تجاهل المحادثات الخاصة
    if chat.type == "private":
        return None

    # فحص القابلية للنشر
    can_post, reason = await test_post_permission(client, chat_id, test_message)

    # مغادرة القنوات دائمًا في وضع Auto-Leave
    if auto_leave and chat.type in ["channel", "supergroup"]:
        if not can_post:
            try:
                await client.leave_chat(chat_id)
                return {
                    "id": chat_id,
                    "name": title,
                    "type": chat.type,
                    "status": "left",
                    "reason": "🚪 Left (Not allowed to post)"
                }
            except Exception as e:
                return {
                    "id": chat_id,
                    "name": title,
                    "status": "error",
                    "reason": str(e)
                }

    return {
        "id": chat_id,
        "name": title,
        "type": chat.type,
        "status": "ok" if can_post else "restricted",
        "reason": reason,
        "can_post": can_post
    }


# ======================================================
# 📊 فحص جميع المجموعات
# ======================================================
async def scan_all_groups_pyrogram(phone, test_message, auto_leave):
    acc = get_account(phone)
    if not acc:
        return {"error": "Account not found"}

    session_string = acc["session"]
    api_id = acc["api_id"]
    api_hash = acc["api_hash"]

    client = Client(
        name=phone,
        session_string=session_string,
        api_id=api_id,
        api_hash=api_hash
    )

    results = []
    try:
        await client.connect()
        dialogs = await client.get_dialogs()

        for d in dialogs:
            info = await analyze_dialog(client, d, test_message, auto_leave)
            if info:
                results.append(info)

        await client.disconnect()

        return {"groups": results}

    except Exception as e:
        return {"error": str(e)}


# ======================================================
# 🌐 API – فحص جميع المجموعات
# ======================================================
@sgroups_bp.route("/scan-groups", methods=["POST"])
def scan_groups_route():
    data = request.json
    phone = data.get("session_name")  # اسم الحقل من الواجهة
    test_message = data.get("test_message", "🔷 Test message")
    auto_leave = data.get("auto_leave_on_fail", False)

    if not phone:
        return jsonify({"ok": False, "error": "Missing session_name"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        scan_all_groups_pyrogram(phone, test_message, auto_leave)
    )

    return jsonify({"ok": True, "data": result})
