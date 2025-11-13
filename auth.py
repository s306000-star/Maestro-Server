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
    return f"+{digits}" if not raw.startswith("+") else f"+{digits}"

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

def _load_temp(phone: str) -> dict | None:
    """تحميل الحالة المؤقتة من القرص إن وجدت."""
    path = _tmp_auth_file(phone)
    if not os.path.exists(path):
        return None
    try:
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
# بدء إضافة/حفظ الحساب
# -----------------------------
@auth_bp.route('/save-account', methods=['POST'])
@auth_bp.route('/Save-Account', methods=['POST'])  # دعم شكل آخر لو أرسله الواجهة
def save_account_route():
    """
    نقطة البداية لإضافة حساب جديد: تحفظ الإعدادات الأولية وتبدأ إرسال الكود.
    body: { apiId, apiHash, phone }
    """
    data = request.json or {}
    api_id = data.get('apiId') or data.get('api_id')
    api_hash = data.get('apiHash') or data.get('api_hash')
    phone = _normalize_phone(data.get('phone'))

    if not all([api_id, api_hash, phone]):
        return format_response(success=False, error="Missing required fields (apiId, apiHash, phone).", code=400)

    # حفظ الإعدادات الأولية (تستعمل لاحقًا بعد النجاح)
    save_session_config(phone, api_id, api_hash)

    return run_in_new_loop(_initiate_auth(phone, api_id, api_hash))

async def _initiate_auth(phone: str, api_id: int, api_hash: str):
    """
    يتصل، ويرسل كود التحقق، ويحفظ phone_code_hash + اسم الجلسة المؤقتة.
    """
    base_name = f"web_session_{phone}"
    session_path_no_ext = str(get_session_path(base_name, ""))  # بدون .session
    client = TelegramClient(session_path_no_ext, int(api_id), str(api_hash))

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

    except Exception as e:
        logging.error(f"Auth initiation failed for {phone}: {e}")
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        _drop_mem_state(phone)
        _cleanup_temp(phone)
        return format_response(success=False, error=str(e), code=500)

# -----------------------------
# إعادة إرسال الكود اختياريًا
# -----------------------------
@auth_bp.route('/resend-code', methods=['POST'])
def resend_code_route():
    """
    body: { phone }
    """
    data = request.json or {}
    phone = _normalize_phone(data.get("phone"))
    if not phone:
        return format_response(success=False, error="Missing phone.", code=400)

    # حمّل الإعدادات
    cfg = load_session_config(phone)
    if not cfg:
        return format_response(success=False, error="Account config not found. Save account first.", code=404)

    return run_in_new_loop(_initiate_auth(phone, cfg['api_id'], cfg['api_hash']))

# -----------------------------
# التحقق/تسجيل الدخول بالكود أو كلمة المرور
# -----------------------------
@auth_bp.route('/login', methods=['POST'])
@auth_bp.route('/Login', methods=['POST'])  # دعم أحرف كبيرة
def login_route():
    """
    body: { phone, code?, password? }
    """
    data = request.json or {}
    phone = _normalize_phone(data.get('phone'))
    code = data.get('code')
    password = data.get('password')

    if not phone or (not code and not password):
        return format_response(success=False, error="Phone and code/password are required.", code=400)

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

    client = TelegramClient(session_path_no_ext, int(cfg['api_id']), str(cfg['api_hash']))

    try:
        await client.connect()

        # كلمة مرور 2FA
        if password:
            await client.sign_in(password=password)
        else:
            if not phone_code_hash:
                # وضّح السبب بدقة (كان هذا سبب الخطأ لديك)
                return format_response(success=False, error="phone_code_hash is missing for code verification. Resend code.", code=400)
            await client.sign_in(phone=phone, code=str(code), phone_code_hash=phone_code_hash)

        me = await client.get_me()

        # نجاح: نظّف كل شيء واحفظ الإعدادات النهائية
        save_session_config(phone, cfg['api_id'], cfg['api_hash'])
        _drop_mem_state(phone)
        _cleanup_temp(phone)

        return format_response(data={'status': 'login_success', 'user': getattr(me, "first_name", "")})

    except errors.SessionPasswordNeededError:
        # الواجهة سترسل password في الخطوة التالية
        return format_response(data={'status': 'password_needed'})
    except errors.PhoneCodeInvalidError:
        return format_response(success=False, error="Invalid code. Try again.", code=400)
    except errors.PhoneCodeExpiredError:
        return format_response(success=False, error="Code expired. Resend code.", code=400)
    except Exception as e:
        logging.error(f"Login verification failed for {phone}: {e}")
        return format_response(success=False, error=str(e), code=500)
    finally:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass