# -*- coding: utf-8 -*-
"""
sessions.py — النظام الموحد للجلسات (Hybrid: Telethon session file + MongoDB storage)
"""

import os
import json
import logging
from flask import current_app, Blueprint, request
from pathlib import Path

sessions_bp = Blueprint("sessions", __name__)

# ============================================
# ✔ 1 — File-based system (needed for Telethon login)
# ============================================

def get_session_path(base_name: str, suffix: str = '.session') -> str:
    folder = current_app.config.get("SESSIONS_FOLDER", "./sessions")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{base_name}{suffix}")


def save_session_config(phone: str, api_id: int, api_hash: str):
    base_name = f"web_session_{phone}"
    config_path = get_session_path(base_name, '.json')
    data = {"phone": phone, "api_id": api_id, "api_hash": api_hash}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return True


def load_session_config(phone: str):
    base_name = f"web_session_{phone}"
    config_path = get_session_path(base_name, '.json')
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

# ============================================
# ✔ 2 — MongoDB based session storage
# ============================================

def mongo():
    return current_app.sessions_collection

def get_session(phone: str):
    return mongo().find_one({"phone": phone}, {"_id": 0})

def save_session_string(phone: str, api_id: int, api_hash: str, session_string: str):
    mongo().update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "api_id": api_id,
            "api_hash": api_hash,
            "session": session_string
        }},
        upsert=True
    )

def delete_session(phone: str):
    mongo().delete_one({"phone": phone})


def get_all_sessions():
    return list(mongo().find({}, {"_id": 0}))

# ============================================
# ✔ 3 — API Endpoints
# ============================================

@sessions_bp.route("/sessions/all", methods=["GET"])
def api_all():
    return {
        "ok": True,
        "accounts": get_all_sessions()
    }


@sessions_bp.route("/sessions/delete", methods=["POST"])
def api_delete():
    phone = request.json.get("phone")
    if not phone:
        return {"ok": False, "error": "Missing phone"}, 400
    delete_session(phone)
    return {"ok": True, "message": "Deleted"}


@sessions_bp.route("/sessions/count", methods=["GET"])
def api_count():
    return {"ok": True, "count": len(get_all_sessions())}
