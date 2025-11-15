# -*- coding: utf-8 -*-
"""
auth.py — Handles Telegram login (send code, sign in, save session)
"""

import os
import json
import logging
from flask import Blueprint, request, jsonify, current_app

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

auth_bp = Blueprint("auth", __name__)

# ============================================================
# Helper: Create Telethon Client
# ============================================================

def create_client(phone, api_id, api_hash, session_str=None):
    if session_str:
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
    else:
        # create empty session
        client = TelegramClient(f"sessions/{phone}", api_id, api_hash)

    return client


# ============================================================
# 🔵 SEND VERIFICATION CODE
# ============================================================

@auth_bp.route('/save-account', methods=['POST'])
@auth_bp.route('/Save-Account', methods=['POST'])
@auth_bp.route('/send_code', methods=['POST'])     # ← frontend uses this
@auth_bp.route('/send-code', methods=['POST'])     # ← support both formats
def send_code_route():

    data = request.json or {}

    # Accept multiple styles from frontend
    phone = data.get("phone") or data.get("phone_number")
    api_id = data.get("api_id") or data.get("apiId")
    api_hash = data.get("api_hash") or data.get("apiHash")

    if not phone or not api_id or not api_hash:
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    try:
        api_id = int(api_id)
    except:
        return jsonify({"ok": False, "error": "Invalid api_id"}), 400

    try:
        client = create_client(phone, api_id, api_hash)
        client.connect()

        sent = client.send_code_request(phone)

        # Save initial config for later
        cfg = {
            "phone": phone,
            "api_id": api_id,
            "api_hash": api_hash
        }

        cfg_path = os.path.join("sessions", f"web_session_{phone}.json")
        os.makedirs("sessions", exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)

        return jsonify({"ok": True, "message": "Code sent", "phone": phone})

    except Exception as e:
        logging.exception("Error in send_code")
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# 🔵 VERIFY CODE / SIGN IN
# ============================================================

@auth_bp.route('/login', methods=['POST'])
@auth_bp.route('/Login', methods=['POST'])
@auth_bp.route('/verify-code', methods=['POST'])    # ← new
@auth_bp.route('/verify_code', methods=['POST'])    # ← new
def verify_code_route():

    data = request.json or {}

    phone = data.get("phone") or data.get("phone_number")
    code = data.get("code") or data.get("verification_code")

    if not phone or not code:
        return jsonify({"ok": False, "error": "Missing phone or code"}), 400

    # load saved API info
    cfg_path = os.path.join("sessions", f"web_session_{phone}.json")

    if not os.path.exists(cfg_path):
        return jsonify({"ok": False, "error": "Session not found"}), 400

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    api_id = cfg["api_id"]
    api_hash = cfg["api_hash"]

    try:
        client = create_client(phone, api_id, api_hash)
        client.connect()

        try:
            client.sign_in(phone, code)
        except SessionPasswordNeededError:
            return jsonify({"ok": False,
                            "error": "2FA password required",
                            "need_password": True}), 403

        # get session string
        session_string = client.session.save()

        # save to Mongo
        col = current_app.sessions_collection
        col.update_one(
            {"phone": phone},
            {"$set": {
                "phone": phone,
                "api_id": api_id,
                "api_hash": api_hash,
                "session": session_string
            }},
            upsert=True
        )

        return jsonify({"ok": True, "message": "Logged in successfully"})

    except Exception as e:
        logging.exception("Error in verify_code")
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# 🔵 VERIFY PASSWORD (2FA)
# ============================================================

@auth_bp.route('/password', methods=['POST'])
def password_route():

    data = request.json or {}

    phone = data.get("phone")
    password = data.get("password")

    if not phone or not password:
        return jsonify({"ok": False, "error": "Missing phone or password"}), 400

    cfg_path = os.path.join("sessions", f"web_session_{phone}.json")

    if not os.path.exists(cfg_path):
        return jsonify({"ok": False, "error": "Session not found"}), 400

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    api_id = cfg["api_id"]
    api_hash = cfg["api_hash"]

    try:
        client = create_client(phone, api_id, api_hash)
        client.connect()

        client.sign_in(password=password)

        session_string = client.session.save()

        col = current_app.sessions_collection
        col.update_one(
            {"phone": phone},
            {"$set": {
                "phone": phone,
                "api_id": api_id,
                "api_hash": api_hash,
                "session": session_string
            }},
            upsert=True
        )

        return jsonify({"ok": True, "message": "Password verified"})

    except Exception as e:
        logging.exception("Error in password auth")
        return jsonify({"ok": False, "error": str(e)}), 500
