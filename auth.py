# -*- coding: utf-8 -*-
"""
auth.py — Final Stable Version (Telethon + Auto-Recovery After Restart)
Fully compatible with front-end & Render auto-restarts
"""

from flask import Blueprint, request
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
import logging, os, json, time

from utils import format_response, run_in_new_loop
from sessions import get_session_path, save_session_config, load_session_config
from config import APP_CONFIG

auth_bp = Blueprint("auth", __name__)

# =====================================================================
# Helpers
# =====================================================================

def _normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return f"+{digits}"


def _tmp_auth_file(phone: str) -> str:
    fname = f"tmp_auth_{phone.replace('+','')}.json"
    return os.path.join(APP_CONFIG["SESSIONS_FOLDER"], fname)


def _persist_temp(phone: str, data: dict):
    try:
        with open(_tmp_auth_file(phone), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"[AUTH] Failed to persist temp state: {e}")


def _load_temp(phone: str):
    try:
        path = _tmp_auth_file(phone)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
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


# الذاكرة المؤقتة (ستفقد عند restart، لذلك القرص مهم جداً)
_temp_clients = {}


def _set_mem_state(phone, **kwargs):
    state = _temp_clients.get(phone, {})
    state.update(kwargs)
    _temp_clients[phone] = state


def _get_mem_state(phone):
    return _temp_clients.get(phone)


def _drop_mem_state(phone):
    if phone in _temp_clients:
        del _temp_clients[phone]


def _make_client(session, api_id, api_hash):
    return TelegramClient(session, api_id, api_hash)


# =====================================================================
# Save Account → Send Verification Code
# =====================================================================
@auth_bp.route("/save-account", methods=["POST"])
@auth_bp.route("/Save-Account", methods=["POST"])
def save_account_route():
    data = request.json or {}

    api_id = data.get("apiId") or data.get("api_id")
    api_hash = data.get("apiHash") or data.get("api_hash")
    raw_phone = data.get("phone") or data.get("phone_number")

    phone = _normalize_phone(raw_phone)

    if not api_id or not api_hash or not phone:
        return format_response(False,
            "Missing fields (apiId/api_id, apiHash/api_hash, phone/phone_number)",
            400
        )

    save_session_config(phone, api_id, api_hash)

    return run_in_new_loop(_initiate_auth(phone, int(api_id), str(api_hash)))


async def _initiate_auth(phone, api_id, api_hash):

    session_path = get_session_path(phone).replace(".session", "")
    client = _make_client(session_path, api_id, api_hash)

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return format_response(data={"status": "already_authorized", "user": me.first_name})

        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash

        # حفظ حالة التحقق
        _set_mem_state(phone,
                       client=session_path,
                       phone_code_hash=phone_code_hash,
                       ts=time.time())

        _persist_temp(phone, {
            "session_path": session_path,
            "phone_code_hash": phone_code_hash,
            "api_id": api_id,
            "api_hash": api_hash,
            "ts": time.time()
        })

        await client.disconnect()
        return format_response(data={"status": "code_sent"})

    except errors.PhoneNumberInvalidError:
        return format_response(False, "Invalid phone number.", 400)

    except Exception as e:
        logging.exception(f"[AUTH] Initiate error: {e}")
        return format_response(False, str(e), 500)


# =====================================================================
# Resend Code
# =====================================================================
@auth_bp.route("/resend-code", methods=["POST"])
def resend_code_route():
    data = request.json or {}
    phone = _normalize_phone(data.get("phone") or data.get("phone_number"))

    if not phone:
        return format_response(False, "Missing phone", 400)

    cfg = load_session_config(phone)
    if not cfg:
        return format_response(False, "Account not found", 404)

    return run_in_new_loop(_initiate_auth(phone, int(cfg["api_id"]), str(cfg["api_hash"])))


# =====================================================================
# Login = Verify Code / Password
# =====================================================================
@auth_bp.route("/login", methods=["POST"])
@auth_bp.route("/Login", methods=["POST"])
@auth_bp.route("/verify-code", methods=["POST"])
def login_route():
    data = request.json or {}

    raw_phone = data.get("phone") or data.get("phone_number")
    phone = _normalize_phone(raw_phone)

    code = (
        data.get("code")
        or data.get("phone_code")
        or data.get("verification_code")
        or data.get("otp")
    )

    password = data.get("password")

    if not phone:
        return format_response(False, "Missing phone_number", 400)

    if not code and not password:
        return format_response(False, "Missing verification code or password", 400)

    logging.info(f"[AUTH] Login attempt phone={phone}")

    return run_in_new_loop(_verify_login(phone, code, password))


async def _verify_login(phone, code, password):

    mem = _get_mem_state(phone)

    # محاولة استرجاع الحالة من القرص في حال السيرفر عمل Restart
    if not mem:
        file_state = _load_temp(phone)
        if file_state:
            mem = {
                "client": file_state["session_path"],
                "phone_code_hash": file_state["phone_code_hash"]
            }
            _set_mem_state(phone, **mem)

    if not mem:
        return format_response(False, "Session expired. Please resend code.", 400)

    session_path = mem["client"]
    phone_code_hash = mem.get("phone_code_hash")

    # تحميل إعدادات الحساب
    cfg = load_session_config(phone)
    if not cfg:
        return format_response(False, "Account config not found", 404)

    client = _make_client(session_path, int(cfg["api_id"]), str(cfg["api_hash"]))

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            _drop_mem_state(phone)
            _cleanup_temp(phone)
            return format_response(data={"status": "already_authorized", "user": me.first_name})

        if password:
            await client.sign_in(phone=phone, password=password)
        else:
            if not phone_code_hash:
                return format_response(False, "Missing phone_code_hash", 400)

            await client.sign_in(
                phone=phone,
                code=str(code),
                phone_code_hash=phone_code_hash
            )

        me = await client.get_me()
        string_session = StringSession.save(client.session)

        # حذف البيانات المؤقتة
        _drop_mem_state(phone)
        _cleanup_temp(phone)

        return format_response(data={
            "status": "logged_in",
            "user_id": me.id,
            "first_name": me.first_name,
            "session_string": string_session
        })

    except errors.PhoneCodeInvalidError:
        return format_response(False, "Invalid verification code", 400)

    except errors.SessionPasswordNeededError:
        return format_response(False, "Password (2FA) required", 401)

    except Exception as e:
        logging.exception(f"[AUTH] Error: {e}")
        return format_response(False, str(e), 500)

    finally:
        await client.disconnect()
