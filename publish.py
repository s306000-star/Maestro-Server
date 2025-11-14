# -*- coding: utf-8 -*-
"""
publish.py — Smart Publishing (MongoDB + Pyrogram Edition)
"""

from flask import Blueprint, request, jsonify, current_app
import asyncio
import random
import logging

from pyrogram import Client, errors

publish_bp = Blueprint("publish", __name__)

# ==================================================================
# 🔧 جلب حساب من MongoDB
# ==================================================================
def get_account(phone):
    col = current_app.sessions_collection
    return col.find_one({"phone": phone})


# ==================================================================
# 📌 نشر رسالة على مجموعة واحدة
# ==================================================================
async def send_message_to_group(session_data, group_id, message):
    client = Client(
        name=session_data["phone"],
        session_string=session_data["session"],
        api_id=session_data["api_id"],
        api_hash=session_data["api_hash"]
    )

    try:
        await client.connect()
        await client.send_message(group_id, message)
        await client.disconnect()

        return {"status": "sent", "group": group_id}

    except Exception as e:
        return {"status": "error", "group": group_id, "error": str(e)}


# ==================================================================
# 📌 جلب جميع مجموعات الحساب (Force All)
# ==================================================================
async def fetch_groups(session_data):
    client = Client(
        name=session_data["phone"],
        session_string=session_data["session"],
        api_id=session_data["api_id"],
        api_hash=session_data["api_hash"]
    )

    groups = []

    try:
        await client.connect()
        dialogs = await client.get_dialogs()

        for d in dialogs:
            if d.chat.type in ["supergroup", "group", "channel"]:
                groups.append(d.chat.id)

        await client.disconnect()
        return groups

    except Exception as e:
        return {"error": str(e)}


# ==================================================================
# 📌 بدء نشر لحساب معيّن
# ==================================================================
async def start_campaign_for_account(phone, messages, groups, settings):
    session_data = get_account(phone)
    if not session_data:
        logging.error(f"No session found for {phone}")
        return

    delay = int(settings.get("message_delay", 10))
    is_force_all = settings.get("is_force_all", False)

    # ---------------------------------------------------------
    # 🟦 Force All → اجلب مجموعات الحساب
    # ---------------------------------------------------------
    if is_force_all:
        groups = await fetch_groups(session_data)
        if "error" in groups:
            logging.error(f"Failed to fetch groups for {phone}")
            return

    # ---------------------------------------------------------
    # 🟦 لا توجد مجموعات
    # ---------------------------------------------------------
    if not groups:
        logging.warning(f"No groups to publish for account {phone}")
        return

    logging.info(f"📢 Campaign started for {phone} on {len(groups)} groups")

    # ---------------------------------------------------------
    # 🟦 تنفيذ النشر
    # ---------------------------------------------------------
    for target in groups:
        message = random.choice(messages)

        result = await send_message_to_group(session_data, target, message)

        logging.info(f"Sent to {target}: {result}")

        await asyncio.sleep(delay)

    logging.info(f"🏁 Campaign finished for {phone}")


# ==================================================================
# 🌐 API — تشغيل حملة نشر
# ==================================================================
@publish_bp.route("/publish", methods=["POST"])
def publish_route():
    data = request.json or {}

    accounts = data.get("accounts", [])
    messages = data.get("messages", [])
    groups = data.get("groups", [])
    settings = data.get("settings", {})

    if not accounts or not messages:
        return jsonify({"ok": False, "error": "accounts and messages required"}), 400

    # ---------------------------------------------------------
    # 🧵 تشغيل حملة لكل حساب
    # ---------------------------------------------------------
    for acc in accounts:
        phone = acc.get("session_id") or acc.get("phone")
        if not phone:
            continue

        # حذف web_session_ إن وجد
        phone = phone.replace("web_session_", "")

        asyncio.get_event_loop().create_task(
            start_campaign_for_account(phone, messages, groups, settings)
        )

    return jsonify({
        "ok": True,
        "message": f"Campaign started for {len(accounts)} accounts."
    })
