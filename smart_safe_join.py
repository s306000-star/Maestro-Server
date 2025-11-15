# -*- coding: utf-8 -*-
"""
smart_safe_join.py — Smart & Safe Join (Pyrogram + MongoDB Edition)
Final Production Version — Fully Compatible with app.py + MongoDB + Render
"""

from flask import Blueprint, request, jsonify, current_app
from pyrogram import Client, errors
import asyncio
import re
import random


# ============================================================
# 🟢 Correct Blueprint Name (Required by app.py)
# ============================================================
smart_safe_join_bp = Blueprint("smart_safe_join", __name__)


# ============================================================
# 📌 Fetch account from MongoDB
# ============================================================
def get_account(phone):
    col = current_app.sessions_collection
    return col.find_one({"phone": phone})


# ============================================================
# 🔍 Extract links from text
# ============================================================
INVITE_RE = re.compile(r"(?:https?://)?t\.me/(?:\+|joinchat/)?([A-Za-z0-9_-]+)")
USERNAME_RE = re.compile(r"@([A-Za-z0-9_]{5,})")


def extract_links(text):
    invites = INVITE_RE.findall(text)
    usernames = USERNAME_RE.findall(text)
    return list(set(invites + usernames))


# ============================================================
# 🔑 Try joining a single link
# ============================================================
async def join_single(client, token, safe_mode=True):
    try:
        # username
        if token.isalnum() and not token.startswith("+"):
            chat = await client.get_chat(token)

            if safe_mode and chat.type == "channel":
                return {"status": "skipped", "reason": "channel_blocked"}

            await client.join_chat(token)
            return {"status": "joined", "type": chat.type}

        # invite hash
        else:
            info = None
            if safe_mode:
                try:
                    info = await client.get_chat(token)
                    if info.type == "channel":
                        return {"status": "skipped", "reason": "channel_blocked"}
                except:
                    # ignore invalid invite pre-check under safe mode
                    info = None

            await client.join_chat(token)
            return {"status": "joined", "type": "invite_link"}

    except errors.UserAlreadyParticipant:
        return {"status": "already"}

    except errors.FloodWait as fw:
        return {"status": "flood", "wait": fw.value}

    except Exception as e:
        return {"status": "failed", "reason": str(e)}


# ============================================================
# 🚀 Smart Join Runner
# ============================================================
async def smart_join_runner(session_data, links, mode="smart"):
    safe_mode = (mode == "safe")

    # Ensure correct session field name from MongoDB
    session_string = session_data.get("session") or session_data.get("session_string")

    client = Client(
        name=session_data["phone"],
        session_string=session_string,
        api_id=session_data["api_id"],
        api_hash=session_data["api_hash"]
    )

    results = []

    await client.connect()

    for token in links:
        result = await join_single(client, token, safe_mode)
        results.append({"token": token, "result": result})

        # Smart mode = faster, Safe mode = slower
        await asyncio.sleep(
            random.uniform(2, 5) if mode == "smart" else random.uniform(5, 8)
        )

    await client.disconnect()
    return results


# ============================================================
# 🌐 API Endpoint — Smart Join / Safe Join
# ============================================================
@smart_safe_join_bp.route("/join/smart", methods=["POST"])
def smart_join_api():
    payload = request.json or {}

    session_name = payload.get("session_name")
    mode = payload.get("mode", "smart")
    text = payload.get("links") or ""

    if not session_name:
        return jsonify({"ok": False, "error": "Missing session_name"}), 400

    # Extract phone (ensure '+' exists)
    digits = session_name.replace("web_session_", "")
    phone = "+" + digits if not digits.startswith("+") else digits

    # Fetch the user session from MongoDB
    acc = get_account(phone)
    if not acc:
        return jsonify({"ok": False, "error": "Account not found"}), 404

    # Extract links from text
    links = extract_links(text)
    if not links:
        return jsonify({"ok": False, "error": "No valid links found"}), 400

    # Run async logic
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    data = loop.run_until_complete(
        smart_join_runner(acc, links, mode)
    )

    return jsonify({"ok": True, "data": data})
