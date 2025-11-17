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

def _get_temp_session_path(phone: str) -> str:
    """Returns the path for the temporary session file."""
    folder = "./sessions"
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"tmp_auth_{phone.replace('+', '')}")

def _cleanup_temp_files(phone: str):
    """Deletes temporary session files."""
    session_path = _get_temp_session_path(phone)
    for ext in [".session", ".session-journal"]:
        try:
            f_path = f"{session_path}{ext}"
            if os.path.exists(f_path):
                os.remove(f_path)
                logging.info(f"Cleaned up {f_path}")
        except Exception as e:
            logging.warning(f"Failed to cleanup temp file for {phone}: {e}")

# ============================================================
# حفظ الحساب وبدء إرسال الكود  (المسار الرسمي الجديد)
# ============================================================
@auth_bp.route("/save-account", methods=["POST"])
@auth_bp.route("/Save-Account", methods=["POST"])
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

    api_id = data.get("api_id") or data.get("apiId")
    api_hash = data.get("api_hash") or data.get("apiHash")
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
    يتصل، ويرسل كود التحقق، ويحفظ phone_code_hash مؤقتًا.
    """
    session_path = _get_temp_session_path(phone)
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        logging.info(f"Connecting client for {phone} to send code...")
        await client.connect()

        # إرسال الكود
        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash
        logging.info(f"Code sent successfully to {phone}.")
        
        return format_response(data={"status": "code_sent", "phone_code_hash": phone_code_hash})

    except errors.PhoneNumberInvalidError:
        logging.error(f"Invalid phone number: {phone}")
        return format_response(
            success=False, error="Invalid phone number.", code=400
        )
    except Exception as e:
        logging.exception(f"Error during initiate_auth for {phone}: {e}")
        return format_response(success=False, error=str(e), code=500)
    finally:
        if client.is_connected():
            await client.disconnect()
            logging.info(f"Client for {phone} disconnected.")


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
      - { phone, password, phone_code_hash }
    """
    data = request.json or {}

    raw_phone = data.get("phone")
    phone = _normalize_phone(raw_phone)

    code = data.get("code")
    password = data.get("password")
    phone_code_hash = data.get("phone_code_hash")

    if not phone or (not code and not password) or not phone_code_hash:
        return format_response(
            success=False,
            error="Phone, phone_code_hash, and either code or password are required.",
            code=400,
        )

    logging.info(
        f"[AUTH] Login attempt for phone={phone}, has_code={bool(code)}, has_password={bool(password)}"
    )

    return run_in_new_loop(_verify_login(phone, code, password, phone_code_hash))


async def _verify_login(phone: str, code: str | None, password: str | None, phone_code_hash: str):
    
    cfg = load_session_config(phone)
    if not cfg:
        return format_response(
            success=False,
            error="Account config not found. Save account first.",
            code=404,
        )

    api_id = int(cfg["api_id"])
    api_hash = str(cfg["api_hash"])

    # Use the temporary file session for this process
    session_path = _get_temp_session_path(phone)
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()

        if password:
            await client.sign_in(password=password)
        else:
            await client.sign_in(
                phone=phone, code=str(code), phone_code_hash=phone_code_hash
            )

        me = await client.get_me()

        # حفظ الكونفيج + StringSession
        string_session = client.session.save()
        save_session_string(phone, api_id, api_hash, string_session)
        
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
        # Clean up temporary files after the process is complete
        _cleanup_temp_files(phone)
