# -*- coding: utf-8 -*-
"""
sessions.py - دوال لإدارة جلسات تليجرام
"""

import os
import json
import logging
from pathlib import Path
from flask import Blueprint, request
from telethon import TelegramClient
import tempfile
import shutil

from config import CONFIG
from utils import format_response, read_json_safe, write_json_safe

sessions_bp = Blueprint('sessions', __name__)

SESSIONS_DIR = CONFIG['SESSIONS_FOLDER']

def get_session_path(base_name: str, suffix: str = '.session') -> str:
    """
    إرجاع المسار الكامل لملف الجلسة بناءً على الاسم الأساسي.
    """
    return os.path.join(SESSIONS_DIR, f"{base_name}{suffix}")

def load_session_config_by_name(base_name: str) -> dict | None:
    """
    تحميل إعدادات الجلسة (api_id, api_hash) من ملف JSON باستخدام الاسم الأساسي.
    """
    config_path = get_session_path(base_name, '.json')
    return read_json_safe(config_path)

def save_session_config(phone: str, api_id: int, api_hash: str):
    """
    حفظ إعدادات الجلسة في ملف JSON.
    """
    base_name = f"web_session_{phone}"
    config_path = get_session_path(base_name, '.json')
    config_data = {'api_id': api_id, 'api_hash': api_hash, 'phone': phone}
    return write_json_safe(config_path, config_data)

def get_all_sessions() -> list:
    """
    إرجاع قائمة بجميع أسماء الجلسات المحفوظة والكاملة.
    (يجب أن يحتوي الحساب على ملف .session و .json)
    """
    sessions = []
    if not os.path.exists(SESSIONS_DIR):
        logging.warning(f"Sessions directory not found at: {SESSIONS_DIR}")
        return []
        
    for f in os.listdir(SESSIONS_DIR):
        if f.endswith('.session'):
            base_name = f.replace('.session', '')
            # التأكد من وجود ملف الإعدادات .json المقابل
            if os.path.exists(get_session_path(base_name, '.json')):
                sessions.append(base_name)
            else:
                logging.warning(f"Session file '{f}' found, but config file '{base_name}.json' is missing. Skipping.")
    return sessions

def delete_session(base_name: str) -> bool:
    """
    حذف ملف الجلسة (.session) وملف الإعدادات (.json).
    """
    session_file = get_session_path(base_name, '.session')
    config_file = get_session_path(base_name, '.json')
    
    session_exists = os.path.exists(session_file)
    config_exists = os.path.exists(config_file)

    if not session_exists and not config_exists:
        logging.warning(f"No session files found to delete for {base_name}")
        return True # Considered success as there's nothing to delete

    try:
        if session_exists:
            os.remove(session_file)
            logging.info(f"Deleted session file for {base_name}")
        if config_exists:
            os.remove(config_file)
            logging.info(f"Deleted config file for {base_name}")
        return True
    except OSError as e:
        logging.error(f"Error during file deletion for {base_name}: {e}")
        return False

def load_session_config(phone: str) -> dict | None:
    """
    Helper function to maintain compatibility.
    """
    base_name = f"web_session_{phone}"
    return load_session_config_by_name(base_name)

async def run_with_safe_clone(base_name: str, task_callback):
    """
    إنشاء نسخة مؤقتة وآمنة من الجلسة لتنفيذ مهمة معينة.
    """
    config = load_session_config_by_name(base_name)
    if not config:
        raise FileNotFoundError(f"Session config not found for {base_name}")

    original_session_path = get_session_path(base_name)
    if not os.path.exists(original_session_path):
        raise FileNotFoundError(f"Session file not found for {base_name}: {original_session_path}")

    temp_dir = tempfile.mkdtemp(prefix="tg_clone_")
    cloned_session_path = os.path.join(temp_dir, os.path.basename(original_session_path))
    
    client = None
    try:
        shutil.copy2(original_session_path, cloned_session_path)
        
        client = TelegramClient(
            cloned_session_path.replace(".session", ""),
            int(config['api_id']),
            config['api_hash']
        )
        
        await client.connect()
        if not await client.is_user_authorized():
            raise PermissionError("Client session is not authorized.")
            
        result = await task_callback(client)
        return result
        
    finally:
        if client and client.is_connected():
            await client.disconnect()
        # Ensure the temporary directory is always removed
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logging.debug(f"Cleaned up temporary directory: {temp_dir}")

# --- API Routes for sessions ---

@sessions_bp.route('/get-accounts', methods=['GET'])
def get_accounts_route():
    """
    جلب قائمة بجميع الحسابات (الجلسات) المحفوظة والجاهزة للاستخدام.
    """
    try:
        session_names = get_all_sessions()
        accounts_data = []
        for name in session_names:
            config = load_session_config_by_name(name)
            if config:
                accounts_data.append({
                    "phone": config.get('phone'),
                    "apiId": config.get('api_id'),
                    "apiHash": config.get('api_hash'),
                    "status": "ready"
                })
        return format_response(data={'accounts': accounts_data})
    except Exception as e:
        logging.error(f"Failed to get accounts: {e}")
        return format_response(success=False, error=str(e), code=500)


@sessions_bp.route('/get-active-accounts', methods=['GET'])
def get_active_accounts():
    """
    تفحص مجلد sessions وتُرجع فقط الحسابات التي تملك ملفات جلسة وإعدادات كاملة.
    """
    try:
        session_names = get_all_sessions()
        accounts_data = []
        for name in session_names:
            config = load_session_config_by_name(name)
            if config and 'phone' in config:
                accounts_data.append(config['phone'])

        accounts_data = sorted(accounts_data, reverse=True)
        return format_response(data={"active_accounts": accounts_data})
    except Exception as e:
        logging.error(f"Error scanning sessions folder: {e}")
        return format_response(success=False, error=str(e), code=500)


@sessions_bp.route('/delete-account', methods=['POST'])
def delete_account_route():
    """
    حذف حساب (جلسة) معينة.
    """
    try:
        data = request.get_json(silent=True) or {}
        phone = data.get('phone')
        
        if not phone:
            return format_response(success=False, error="❌ Missing phone number.", code=400)
        
        base_name = f"web_session_{phone}"
        success = delete_session(base_name)

        if success:
            return format_response(data={"message": f"✅ Deleted session file(s) for '{phone}'."})
        else:
            return format_response(data={"message": f"✅ No session files found for '{phone}', considered deleted."})
            
    except Exception as e:
        logging.error(f"Error deleting account: {e}")
        return format_response(success=False, error=str(e), code=500)

