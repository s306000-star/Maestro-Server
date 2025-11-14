# -*- coding: utf-8 -*-
"""
filters.py — MongoDB + Pyrogram Edition
(يحل محل Telethon بالكامل)
"""

from flask import Blueprint, request, jsonify, current_app
from pyrogram import Client, errors
import asyncio

filters_bp = Blueprint("filters", __name__)


# ============================================================
# 🔧 جلب حساب من MongoDB
# ============================================================

def get_account(phone):
    col = current_app.sessions_collection
    return col.find_one({"phone": phone})


# ============================================================
# 🧠 فحص صلاحيات النشر
# ============================================================

async def check_post_permission(client, chat_id):
    try:
        await client.send_message(chat_id, "🔹 Test Message")
        return True, "✔️ Allowed to post"
    except errors.ChatWriteForbidden:
        return False, "❌ Not allowed to write"
    except errors.UserBannedInChannel:
        return False, "⛔ User banned"
    except Exception as e:
        return False, str(e)


# ============================================================
# 🧩 تحليل مجموعة أو قناة
# ============================================================

async def analyze_group(client, dialog):
    chat = dialog.chat
    chat_id = chat.id
    title = chat.title or "Unknown"
    chat_type = chat.type

    # تجاهل الدردشة الخاصة
    if chat_type == "private":
        return None

    # فحص النشر
    can_post, reason = await check_post_permission(client, chat_id)

    # رابط دعوة (إن وجد)
    invite = ""
    if chat.username:
        invite = f"https://t.me/{chat.username}"

    return {
        "id": chat_id,
        "title": title,
        "type": chat_type,
        "invite_link": invite,
        "can_post": can_post,
        "reason": reason
    }


# ============================================================
# 🔍 Deep Scan (بديل Telethon Deep Scan)
# ============================================================

async def deep_scan(phone):
    acc = get_account(phone)
    if not acc:
        return {"error": "Account not found"}

    client = Client(
        name=phone,
        session_string=acc["session"],
        api_id=acc["api_id"],
        api_hash=acc["api_hash"]
    )

    results = []

    await client.connect()
    dialogs = await client.get_dialogs()

    for d in dialogs:
        info = await analyze_group(client, d)
        if info:
            results.append(info)

    await client.disconnect()

    return {"groups": results}


# ============================================================
# 🌐 API: فحص كل المجموعات
# ============================================================

@filters_bp.route("/filters/scan", methods=["POST"])
def scan_route():
    data = request.json
    phone = data.get("phone")

    if not phone:
        return jsonify({"ok": False, "error": "Missing phone"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    result = loop.run_until_complete(deep_scan(phone))

    return jsonify({"ok": True, "data": result})


# ============================================================
# 🚪 مغادرة مجموعة
# ============================================================

async def leave_group_action(client, chat_id):
    try:
        await client.leave_chat(chat_id)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@filters_bp.route("/filters/leave", methods=["POST"])
def leave_route():
    data = request.json
    phone = data.get("phone")
    chat_id = data.get("group_id")

    if not phone or not chat_id:
        return jsonify({"ok": False, "error": "Missing phone or group_id"}), 400

    acc = get_account(phone)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    client = Client(
        name=phone,
        session_string=acc["session"],
        api_id=acc["api_id"],
        api_hash=acc["api_hash"]
    )

    async def runner():
        await client.connect()
        res = await leave_group_action(client, chat_id)
        await client.disconnect()
        return res

    result = loop.run_until_complete(runner())

    return jsonify({"ok": True, "data": result})


# ============================================================
# ➕ الانضمام إلى مجموعة
# ============================================================

@filters_bp.route("/filters/join", methods=["POST"])
def join_route():
    data = request.json
    phone = data.get("phone")
    link = data.get("link")

    if not phone or not link:
        return jsonify({"ok": False, "error": "Missing phone or link"}), 400

    acc = get_account(phone)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    client = Client(
        name=phone,
        session_string=acc["session"],
        api_id=acc["api_id"],
        api_hash=acc["api_hash"]
    )

    async def runner():
        await client.connect()
        try:
            chat = await client.join_chat(link)
            await client.disconnect()
            return {"status": "success", "chat_id": chat.id}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    result = loop.run_until_complete(runner())

    return jsonify({"ok": True, "data": result})
