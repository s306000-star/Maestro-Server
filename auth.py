# -*- coding: utf-8 -*-
"""
auth.py - Blueprint لإدارة المصادقة وإضافة الحسابات (محسّن مع تخزين مؤقت على القرص)
"""

from flask import Blueprint, request
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
import logging, os, json, time

from utils import format_response, run_in_new_loop
from sessions import get_session_path, save_session_config, load_session_config
from config import APP_CONFIG  # لاستخدام SESSIONS_FOLDER

auth_bp = Blueprint('auth', __name__)

# -----------------------------
# أدوات مساعدة داخلية
# -----------------------------
def _normalize_phone(raw: str) -> str:
    """يوحّد رقم الهاتف إلى صيغة +<digits> بدون مسافات."""
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return f"+{digits}" if not str(raw).startswith("+") else f"+{digits}"

def _tmp_auth_file(phone: str) -> str:
    """مسار ملف الحالة المؤقتة لهذه العملية."""
    fname = f"tmp_auth_{phone.replace('+','')}.json"
    return os.path.join(APP_CONFIG["SESSIONS_FOLDER"], fname)

def _persist_temp(phone: str, data: dict):
    """حفظ الحالة المؤقتة (hash/اسم الجلسة)."""
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

# ملاحظة: أبقينا dict للذاكرة لسرعة الحالة أثناء العملية، لكن أصبح لدينا نسخة احتياطية على القرص.
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

# -----------------------------
# تهيئة عميل تليجرام
# -----------------------------
def _make_client(session_path_no_ext: str, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(session_path_no_ext, api_id, api_hash)

# ============================================================
# حفظ الحساب وبدء إرسال الكود
# ============================================================
@auth_bp.route('/save-account', methods=['POST'])
@auth_bp.route('/Save-Account', methods=['POST'])  # دعم شكل آخر لو أرسله الواجهة
def save_account_route():
    """
    نقطة البداية لإضافة حساب جديد: تحفظ الإعدادات الأولية وتبدأ إرسال الكود.
    body المقبول (أي شكل من الآتي):
      - { apiId, apiHash, phone }
      - { apiId, apiHash, phone_number }
      - { api_id, api_hash, phone }
      - { api_id, api_hash, phone_number }
    هذا يجعل الباكند متوافقًا مع أكثر من واجهة بدون أخطاء Missing fields.
    """
    data = request.json or {}

    # دعم أكثر من شكل للمفاتيح القادمة من الواجهة
    api_id = data.get('apiId') or data.get('api_id')
    api_hash = data.get('apiHash') or data.get('api_hash')

    raw_phone = data.get('phone') or data.get('phone_number')
    phone = _normalize_phone(raw_phone)

    if not all([api_id, api_hash, phone]):
        return format_response(
            success=False,
            error="Missing required fields (apiId/api_id, apiHash/api_hash, phone/phone_number).",
            code=400
        )

    # حفظ الإعدادات الأولية (تستعمل لاحقًا بعد النجاح)
    save_session_config(phone, api_id, api_hash)

    return run_in_new_loop(_initiate_auth(phone, int(api_id), str(api_hash)))

async def _initiate_auth(phone: str, api_id: int, api_hash: str):
    """
    يتصل، ويرسل كود التحقق، ويحفظ phone_code_hash مؤقتًا (في الذاكرة وعلى القرص).
    """
    # مسار الجلسة (بدون الامتداد)
    session_path_no_ext = get_session_path(phone).replace(".session", "")

    client = _make_client(session_path_no_ext, api_id, api_hash)

    try:
        await client.connect()

        # إذا الجلسة قديمة ومصرّح بها بالفعل
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            _drop_mem_state(phone)
            _cleanup_temp(phone)
            return format_response(data={'status': 'already_authorized', 'user': getattr(me, "first_name", "")})

        # إرسال الكود
        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash

        # حفظ الحالة في الذاكرة وعلى القرص
        _set_mem_state(phone, client=session_path_no_ext, phone_code_hash=phone_code_hash, ts=time.time())
        _persist_temp(phone, {
            "session_path_no_ext": session_path_no_ext,
            "phone_code_hash": phone_code_hash,
            "api_id": int(api_id),
            "api_hash": str(api_hash),
            "ts": time.time()
        })

        # لا نغلق الاتصال هنا؛ Telethon سيعيد فتحه تلقائيًا عند load من نفس مسار الجلسة
        await client.disconnect()
        return format_response(data={'status': 'code_sent'})

    except errors.PhoneNumberInvalidError:
        await client.disconnect()
        return format_response(success=False, error="Invalid phone number.", code=400)
    except Exception as e:
        logging.exception(f"Error during initiate_auth for {phone}: {e}")
        await client.disconnect()
        return format_response(success=False, error=str(e), code=500)

# ============================================================
# إعادة إرسال الكود
# ============================================================
@auth_bp.route('/resend-code', methods=['POST'])
def resend_code_route():
    """
    body: { phone } أو { phone_number }
    """
    data = request.json or {}
    phone = _normalize_phone(data.get("phone") or data.get("phone_number"))
    if not phone:
        return format_response(success=False, error="Missing phone.", code=400)

    # حمّل الإعدادات
    cfg = load_session_config(phone)
    if not cfg:
        return format_response(success=False, error="Account config not found. Save account first.", code=404)

    return run_in_new_loop(_initiate_auth(phone, int(cfg['api_id']), str(cfg['api_hash'])))

# ============================================================
# التحقق/تسجيل الدخول بالكود أو كلمة المرور
# ============================================================
@auth_bp.route('/login', methods=['POST'])
@auth_bp.route('/Login', methods=['POST'])  # دعم أحرف كبيرة
@auth_bp.route('/verify-code', methods=['POST'])  # مسار إضافي للتوافق مع بعض الواجهات
def login_route():
    """اكمال تسجيل الدخول بعد إدخال كود التحقق أو كلمة المرور.

    body المقبول:
      - { phone, code }
      - { phone, password }
      - { phone_number, phone_code }
    """
    data = request.json or {}

    # دعم أكثر من اسم لنفس الحقل لتفادي مشاكل front-end
    raw_phone = data.get('phone') or data.get('phone_number')
    phone = _normalize_phone(raw_phone)

    code = data.get('code') or data.get('phone_code')
    password = data.get('password')

    if not phone or (not code and not password):
        return format_response(
            success=False,
            error="Phone (or phone_number) and code/phone_code or password are required.",
            code=400
        )

    # تسجيل Log مبسط لتسهيل تتبع المشاكل في Render
    logging.info(f"[AUTH] Login attempt for phone={phone}, has_code={bool(code)}, has_password={bool(password)}")

    return run_in_new_loop(_verify_login(phone, code, password))

async def _verify_login(phone: str, code: str | None, password: str | None):
    """
    يكمل عملية تسجيل الدخول مع استرجاع الحالة المؤقتة حتى بعد إعادة تشغيل السيرفر.
    """
    # 1) حاول من الذاكرة
    mem_state = _get_mem_state(phone)

    # 2) إن لم توجد حالة في الذاكرة، حاول من القرص
    if not mem_state:
        file_state = _load_temp(phone)
        if file_state:
            mem_state = {
                "client": file_state.get("session_path_no_ext"),
                "phone_code_hash": file_state.get("phone_code_hash"),
                "ts": file_state.get("ts")
            }
            _set_mem_state(phone, **mem_state)

    if not mem_state:
        return format_response(success=False, error="Session expired or invalid. Please start over.", code=400)

    session_path_no_ext = mem_state["client"]
    phone_code_hash = mem_state.get("phone_code_hash")

    # نحتاج API_ID/API_HASH
    cfg = load_session_config(phone)
    if not cfg:
        return format_response(success=False, error="Account config not found. Save account first.", code=404)

    api_id = int(cfg['api_id'])
    api_hash = str(cfg['api_hash'])

    client = _make_client(session_path_no_ext, api_id, api_hash)

    try:
        await client.connect()

        # لو الحساب أصلاً مسجّل دخول
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            _drop_mem_state(phone)
            _cleanup_temp(phone)
            return format_response(data={"status": "already_authorized", "user": getattr(me, "first_name", "")})

        # حالة 2FA
        if password:
            await client.sign_in(phone=phone, password=password)
        else:
            if not phone_code_hash:
                return format_response(
                    success=False,
                    error="phone_code_hash is missing for code verification. Please resend code.",
                    code=400
                )
            await client.sign_in(phone=phone, code=str(code), phone_code_hash=phone_code_hash)

        me = await client.get_me()

        # نجاح: نظّف كل شيء واحفظ الإعدادات النهائية
        save_session_config(phone, api_id, api_hash)
        _drop_mem_state(phone)
        _cleanup_temp(phone)

        # حفظ StringSession لو احتجته مستقبلاً
        string_session = StringSession.save(client.session)
        logging.info(f"[AUTH] Login successful for {phone}")

        return format_response(
            data={
                "status": "logged_in",
                "user_id": me.id,
                "first_name": getattr(me, "first_name", ""),
                "session_string": string_session
            }
        )

    except errors.PhoneCodeInvalidError:
        logging.warning(f"Invalid code for phone {phone}")
        return format_response(success=False, error="Invalid verification code.", code=400)
    except errors.SessionPasswordNeededError:
        logging.warning(f"Password (2FA) required for phone {phone}")
        return format_response(success=False, error="Two-factor authentication enabled. Please provide password.", code=401)
    except Exception as e:
        logging.exception(f"Error during verify_login for {phone}: {e}")
        return format_response(success=False, error=str(e), code=500)
    finally:
        await client.disconnect()
