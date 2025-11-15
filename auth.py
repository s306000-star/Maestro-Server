# -*- coding: utf-8 -*-
"""
auth.py - Blueprint لإدارة المصادقة وإضافة الحسابات
(محسّن مع تخزين مؤقت على القرص + حفظ الجلسة في MongoDB)
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
    save_session_string,   # لحفظ StringSession في MongoDB
)
from config import CONFIG

auth_bp = Blueprint("auth", __name__)

# ===============================
# أدوات مساعدة داخلية
# ===============================

def _normalize_phone(raw: str) -> str:
    """يوحّد رقم الهاتف إلى صيغة +<digits> بدون مسافات."""
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return f"+{digits}"

def _tmp_auth_file(phone: str) -> str:
    """مسار ملف الحالة المؤقتة لهذه العملية."""
    fname = f"tmp_auth_{phone.replace('+','')}.json"
    # Since SESSIONS_FOLDER is removed from config, we define a local temp folder.
    folder = "./sessions"
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, fname)

def _persist_temp(phone: str, data: dict):
    """حفظ الحالة المؤقتة (hash/اسم الجلسة) على القرص."""
    try:
        path = _tmp_auth_file(phone)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"Failed to persist temp auth state for {phone}: {e}")

def _load_temp(phone: str):
    """تحميل الحالة المؤقتة من القرص."""
    path = _tmp_auth_file(phone)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"Failed to load temp auth state for {phone}: {e}")
    return None

def _cleanup_temp(phone: str):
    """حذف الحالة المؤقتة من القرص."""
    path = _tmp_auth_file(phone)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logging.warning(f"Failed to cleanup temp auth for {phone}: {e}")

# حالة مؤقتة في الذاكرة لتسريع العملية
_temp_clients: dict[str, dict] = {}

def _set_mem_state(phone: str, **kwargs):
    state = _temp_clients.get(phone, {})
    state.update(kwargs)
    _temp_clients[phone] = state

def _get_mem_state(phone: str) -> dict | None:
    return _temp_clients.get(phone)

def _drop_mem_state(phone: str):
    if phone in _temp_clients:
        del _temp_clients[phone]

def _make_client(session_path_no_ext: str, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(session_path_no_ext, api_id, api_hash)


# ============================================================
# حفظ الحساب وبدء إرسال الكود  (المسار الرسمي الجديد)
# ============================================================
@auth_bp.route("/save-account", methods=["POST"])
@auth_bp.route("/Save-Account", methods=["POST"])  # دعم شكل آخر لو أرسله front-end
def save_account_route():
    """
    نقطة البداية لإضافة حساب جديد: تحفظ الإعدادات الأولية وتبدأ إرسال الكود.
    body المقبول (أي شكل من الآتي):
      - { apiId, apiHash, phone }
      - { apiId, apiHash, phone_number }
      - { api_id, api_hash, phone }
      - { api_id, api_hash, phone_number }
    """
    data = request.json or {}

    api_id = data.get("apiId") or data.get("api_id")
    api_hash = data.get("apiHash") or data.get("api_hash")
    raw_phone = data.get("phone") or data.get("phone_number") or data.get("phoneNumber")
    phone = _normalize_phone(raw_phone)

    if not all([api_id, api_hash, phone]):
        return format_response(
            success=False,
            error="Missing required fields (apiId/api_id, apiHash/api_hash, phone/phone_number).",
            code=400,
        )

    # حفظ الإعدادات الأولية (تستعمل لاحقًا بعد النجاح)
    save_session_config(phone, api_id, api_hash)

    logging.info(f"[AUTH] save-account for {phone}")
    return run_in_new_loop(_initiate_auth(phone, int(api_id), str(api_hash)))


# ============================================================
# مسار متوافق مع الواجهة القديمة: /auth/send_code
# ============================================================
@auth_bp.route("/send_code", methods=["POST"])
def send_code_compat_route():
    """
    مسار متوافق مع النسخة القديمة من الواجهة التي تستدعي:
      POST /api/auth/send_code
    يعمل بنفس منطق /save-account بالضبط.
    """
    data = request.json or {}

    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    raw_phone = data.get("phone")
    phone = _normalize_phone(raw_phone)

    if not all([api_id, api_hash, phone]):
        return format_response(
            success=False,
            error="Missing required fields: api_id, api_hash, phone.",
            code=400,
        )

    save_session_config(phone, api_id, api_hash)
    logging.info(f"[AUTH] send_code (compat) for {phone}")
    return run_in_new_loop(_initiate_auth(phone, int(api_id), str(api_hash)))


# ============================================================
# تنفيذ إرسال الكود (دالة async داخلية)
# ============================================================
async def _initiate_auth(phone: str, api_id: int, api_hash: str):
    """
    يتصل، ويرسل كود التحقق، ويحفظ phone_code_hash مؤقتًا (في الذاكرة وعلى القرص).
    """
    session_base = f"web_session_{phone}"
    session_path_no_ext = get_session_path(session_base).replace(".session", "")

    client = _make_client(session_path_no_ext, api_id, api_hash)

    try:
        await client.connect()

        # إذا الجلسة قديمة ومصرّح بها بالفعل
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            _drop_mem_state(phone)
            _cleanup_temp(phone)
            return format_response(
                data={
                    "status": "already_authorized",
                    "user": getattr(me, "first_name", ""),
                }
            )

        # إرسال الكود
        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash
        
        # لا نحفظ العميل، فقط الـ hash
        _persist_temp(
            phone,
            {
                "session_path_no_ext": session_path_no_ext,
                "phone_code_hash": phone_code_hash,
                "api_id": int(api_id),
                "api_hash": str(api_hash),
                "ts": time.time(),
            },
        )

        await client.disconnect()
        # إرجاع الـ hash إلى الواجهة الأمامية
        return format_response(data={"status": "code_sent", "phone_code_hash": phone_code_hash})

    except errors.PhoneNumberInvalidError:
        await client.disconnect()
        return format_response(
            success=False, error="Invalid phone number.", code=400
        )
    except Exception as e:
        logging.exception(f"Error during initiate_auth for {phone}: {e}")
        if client.is_connected():
            await client.disconnect()
        return format_response(success=False, error=str(e), code=500)


# ============================================================
# إعادة إرسال الكود
# ============================================================
@auth_bp.route("/resend-code", methods=["POST"])
def resend_code_route():
    data = request.json or {}
    phone = _normalize_phone(data.get("phone") or data.get("phone_number"))
    if not phone:
        return format_response(success=False, error="Missing phone.", code=400)

    cfg = load_session_config(phone)
    if not cfg:
        return format_response(
            success=False,
            error="Account config not found. Save account first.",
            code=404,
        )

    logging.info(f"[AUTH] resend-code for {phone}")
    return run_in_new_loop(
        _initiate_auth(phone, int(cfg["api_id"]), str(cfg["api_hash"]))
    )


# ============================================================
# التحقق/تسجيل الدخول بالكود أو كلمة المرور
# ============================================================
@auth_bp.route("/login", methods=["POST"])
@auth_bp.route("/Login", methods=["POST"])
@auth_bp.route("/verify", methods=["POST"])
def login_route():
    """
    body المقبول:
      - { phone, code, phone_code_hash }
      - { phone, password }
    """
    data = request.json or {}

    raw_phone = data.get("phone")
    phone = _normalize_phone(raw_phone)

    code = data.get("code")
    password = data.get("password")
    phone_code_hash = data.get("phone_code_hash")

    if not phone or (not code and not password):
        return format_response(
            success=False,
            error="Phone and (code with phone_code_hash) or password are required.",
            code=400,
        )

    logging.info(
        f"[AUTH] Login attempt for phone={phone}, has_code={bool(code)}, has_password={bool(password)}"
    )

    return run_in_new_loop(_verify_login(phone, code, password, phone_code_hash))


async def _verify_login(phone: str, code: str | None, password: str | None, phone_code_hash: str | None):
    
    # 1) من القرص لو غير موجود في الذاكرة
    temp_state = _load_temp(phone)
    if not temp_state:
        return format_response(
            success=False,
            error="Session expired or invalid. Please start over by sending code again.",
            code=400,
        )

    session_path_no_ext = temp_state.get("session_path_no_ext")
    if not phone_code_hash:
        phone_code_hash = temp_state.get("phone_code_hash")

    cfg = load_session_config(phone)
    if not cfg:
        return format_response(
            success=False,
            error="Account config not found. Save account first.",
            code=404,
        )

    api_id = int(cfg["api_id"])
    api_hash = str(cfg["api_hash"])

    client = _make_client(session_path_no_ext, api_id, api_hash)

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            _cleanup_temp(phone)
            return format_response(
                data={
                    "status": "already_authorized",
                    "user": getattr(me, "first_name", ""),
                }
            )

        if password:
            await client.sign_in(phone=phone, password=password)
        else:
            if not phone_code_hash:
                return format_response(
                    success=False,
                    error="phone_code_hash is missing. Please start over by sending code again.",
                    code=400,
                )
            await client.sign_in(
                phone=phone, code=str(code), phone_code_hash=phone_code_hash
            )

        me = await client.get_me()

        # حفظ الكونفيج + StringSession
        string_session = client.session.save()
        # Use the new function from the updated sessions.py
        save_session_string(phone, api_id, api_hash, string_session)
        
        _cleanup_temp(phone)

        logging.info(f"[AUTH] Login successful for {phone}")

        return format_response(
            data={
                "status": "login_success",
                "user_id": me.id,
                "user": getattr(me, "first_name", ""),
                "session_string": string_session,
            }
        )

    except errors.PhoneCodeInvalidError:
        logging.warning(f"Invalid code for phone {phone}")
        return format_response(
            success=False, error="Invalid verification code.", code=400
        )
    except errors.SessionPasswordNeededError:
        logging.warning(f"Password (2FA) required for phone {phone}")
        # لا نعتبرها خطأ، بل حالة خاصة للواجهة
        return format_response(data={"status": "2fa_needed"})
    except Exception as e:
        logging.exception(f"Error during verify_login for {phone}: {e}")
        return format_response(success=False, error=str(e), code=500)
    finally:
        if client.is_connected():
            await client.disconnect()

    
@auth_bp.route("/auth/accounts", methods=["GET"])
def get_accounts_route():
    # This is a placeholder as accounts are now fetched from sessions/all
    from sessions import get_all_sessions
    try:
        accounts = get_all_sessions()
        return format_response(data={"accounts": accounts})
    except Exception as e:
        return format_response(success=False, error=str(e), code=500)

    
