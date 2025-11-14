# -*- coding: utf-8 -*-
"""
smart_safe_join.py — Smart & Safe Join (Pyrogram + MongoDB Edition)
"""

from flask import Blueprint, request, jsonify, current_app
from pyrogram import Client, errors
import asyncio, re, random

smart_join_bp = Blueprint("smart_join", __name__)

# ============================================================
# 🔧 جلب الحساب من MongoDB
# ============================================================

def get_account(phone):
    col = current_app.sessions_collection
    return col.find_one({"phone": phone})


# ============================================================
# 🔍 استخراج الروابط من النص
# ============================================================

INVITE_RE = re.compile(r"(?:https?://)?t\.me/(?:\+|joinchat/)?([A-Za-z0-9_-]+)")
USERNAME_RE = re.compile(r"@([A-Za-z0-9_]{5,})")

def extract_links(text):
    invites = INVITE_RE.findall(text)
    usernames = USERNAME_RE.findall(text)
    return list(set(invites + usernames))


# ============================================================
# 🧠 محاولة الانضمام إلى رابط واحد
# ============================================================

async def join_single(client, token, safe_mode=True):
    # token قد يكون username أو invite hash
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
            if safe_mode:
                info = await client.get_chat(token)
                if info.type == "channel":
                    return {"status": "skipped", "reason": "channel_blocked"}

            await client.join_chat(token)
            return {"status": "joined", "type": "invite_link"}

    except errors.UserAlreadyParticipant:
        return {"status": "already"}

    except errors.FloodWait as fw:
        return {"status": "flood", "wait": fw.value}

    except Exception as e:
        return {"status": "failed", "reason": str(e)}


# ============================================================
# 🚀 تنفيذ حملة انضمام كاملة
# ============================================================

async def smart_join_runner(session_data, links, mode="smart"):
    safe_mode = (mode == "safe")

    client = Client(
        name=session_data["phone"],
        session_string=session_data["session"],
        api_id=session_data["api_id"],
        api_hash=session_data["api_hash"]
    )

    results = []

    await client.connect()

    for token in links:
        res = await join_single(client, token, safe_mode)
        results.append({"token": token, "result": res})

        await asyncio.sleep(random.uniform(2, 5) if mode == "smart" else random.uniform(5, 8))

    await client.disconnect()

    return results


# ============================================================
# 🌐 API — Smart Join / Safe Join
# ============================================================

@smart_join_bp.route("/join/smart", methods=["POST"])
def smart_join_api():
    payload = request.json

    session_name = payload.get("session_name")
    mode = payload.get("mode", "smart")
    text = payload.get("links") or ""

    if not session_name:
        return jsonify({"ok": False, "error": "Missing session_name"}), 400

    phone = session_name.replace("web_session_", "")

    acc = get_account(phone)
    if not acc:
        return jsonify({"ok": False, "error": "Account not found"}), 404

    links = extract_links(text)
    if not links:
        return jsonify({"ok": False, "error": "No valid links found"}), 400

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    data = loop.run_until_complete(smart_join_runner(acc, links, mode))

    return jsonify({"ok": True, "data": data})
