# -*- coding: utf-8 -*-
"""
auth.py - Blueprint لإدارة المصادقة وإضافة الحسابات
(محسّن مع تخزين مؤقت على القرص + تخزين الجلسة في MongoDB)
"""

from flask import Blueprint, request
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
import logging, os, json, time

from utils import format_response, run_in_new_loop
from sessions import (
    get_session_path,
    save_session_config,
    load_session_config,
    save_session_string,
)

# ✅ أهم خطوة: إضافة url_prefix حتى تتوافق مع الواجهة
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ===============================
# أدوات مساعدة
# ===============================

def _normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return f"+{digits}"

def _tmp_auth_file(phone: str) -> str:
    fname = f"tmp_auth_{phone.replace('+','')}.json"
    folder = "./sessions"
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, fname)

def _persist_temp(phone: str, data: dict):
    try:
        with open(_tmp_auth_file(phone), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass

def _load_temp(phone: str):
    try:
        path = _tmp_auth_file(phone)
        if os.path.exists(path):
            return json.load(open(path, "r", encoding="utf-8"))
    except:
        pass
    return None

def _cleanup_temp(phone: str):
    try:
        path = _tmp_auth_file(phone)
        if os.path.exists(path):
            os.remove(path)
    except:
        pass

_temp_clients = {}

def _make_client(path_no_ext: str, api_id: int, api_hash: str):
    return TelegramClient(path_no_ext, api_id, api_hash)


# ============================================================
# 1) حفظ الحساب + إرسال الكود
# ============================================================

@auth_bp.route("/save-account", methods=["POST"])
def save_account_route():

    data = request.json or {}
    api_id = data.get("apiId") or data.get("api_id")
    api_hash = data.get("apiHash") or data.get("api_hash")
    raw_phone = data.get("phone") or data.get("phone_number") or data.get("phoneNumber")

    phone = _normalize_phone(raw_phone)

    if not all([api_id, api_hash, phone]):
        return format_response(False, "Missing required fields.", {}, 400)

    save_session_config(phone, api_id, api_hash)

    return run_in_new_loop(_initiate_auth(phone, int(api_id), str(api_hash)))


# ============================================================
# 2) send_code (متوافق مع الواجهة القديمة)
# ============================================================

@auth_bp.route("/send_code", methods=["POST"])
def send_code_compat_route():

    data = request.json or {}
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    phone = _normalize_phone(data.get("phone"))

    if not all([api_id, api_hash, phone]):
        return format_response(False, "Missing api_id / api_hash / phone", {}, 400)

    save_session_config(phone, api_id, api_hash)

    return run_in_new_loop(_initiate_auth(phone, int(api_id), str(api_hash)))


# ============================================================
# 3) دالة إرسال الكود الفعلية
# ============================================================

async def _initiate_auth(phone: str, api_id: int, api_hash: str):

    session_base = f"web_session_{phone}"
    session_path_no_ext = get_session_path(session_base).replace(".session", "")

    client = _make_client(session_path_no_ext, api_id, api_hash)

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            _cleanup_temp(phone)
            return format_response(True, "", {
                "status": "already_authorized",
                "user": getattr(me, "first_name", "")
            })

        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash

        _persist_temp(phone, {
            "session_path_no_ext": session_path_no_ext,
            "phone_code_hash": phone_code_hash,
            "api_id": api_id,
            "api_hash": api_hash,
            "ts": time.time()
        })

        await client.disconnect()

        return format_response(True, "", {
            "status": "code_sent",
            "phone_code_hash": phone_code_hash
        })

    except Exception as e:
        return format_response(False, str(e), {}, 500)


# ============================================================
# 4) تسجيل الدخول بالكود
# ============================================================

@auth_bp.route("/login", methods=["POST"])
def login_route():
    data = request.json or {}

    phone = _normalize_phone(data.get("phone"))
    code = data.get("code")
    password = data.get("password")
    phone_code_hash = data.get("phone_code_hash")

    return run_in_new_loop(_verify_login(phone, code, password, phone_code_hash))


async def _verify_login(phone, code, password, phone_code_hash):

    temp = _load_temp(phone)
    if not temp:
        return format_response(False, "Session expired. Re-send code.", {}, 400)

    session_path_no_ext = temp.get("session_path_no_ext")
    if not phone_code_hash:
        phone_code_hash = temp.get("phone_code_hash")

    cfg = load_session_config(phone)
    api_id = int(cfg["api_id"])
    api_hash = cfg["api_hash"]

    client = _make_client(session_path_no_ext, api_id, api_hash)

    try:
        await client.connect()

        if password:
            await client.sign_in(phone=phone, password=password)
        else:
            await client.sign_in(phone=phone, code=str(code), phone_code_hash=phone_code_hash)

        me = await client.get_me()
        string_session = client.session.save()

        save_session_string(phone, api_id, api_hash, string_session)
        _cleanup_temp(phone)

        return format_response(True, "", {
            "status": "login_success",
            "user_id": me.id,
            "user": getattr(me, "first_name", ""),
            "session_string": string_session
        })

    except errors.PhoneCodeInvalidError:
        return format_response(False, "Invalid verification code.", {}, 400)

    except errors.SessionPasswordNeededError:
        return format_response(True, "", {"status": "2fa_needed"})

    except Exception as e:
        return format_response(False, str(e), {}, 500)

    finally:
        await client.disconnect()
