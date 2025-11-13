# -*- coding: utf-8 -*-
"""
publish.py
إدارة حملات النشر الذكية في Telegram Maestro
"""

import asyncio
import random
import logging
from flask import Blueprint, request

from utils import format_response, run_in_new_loop
from sessions import run_with_safe_clone

publish_bp = Blueprint("publish", __name__)

active_campaigns = {}

@publish_bp.route("/publish", methods=["POST"])
def publish_route():
    data = request.json or {}
    selected_accounts = data.get("accounts", [])
    messages = data.get("messages", [])
    groups = data.get("groups", [])
    settings = data.get("settings", {})

    if not selected_accounts or not messages:
        return format_response(success=False, error="Accounts and messages are required.", code=400)

    for acc in selected_accounts:
        phone = acc.get("session_id", "").replace("web_session_", "")
        if not phone:
            continue
        
        # Use groups if provided, otherwise it will be handled by start_campaign
        assigned_groups = groups

        run_in_new_loop(start_campaign_for_account(phone, messages, assigned_groups, settings))

    return format_response(data={"status": "campaign_started", "message": f"Campaign started for {len(selected_accounts)} accounts."})


async def start_campaign_for_account(phone, messages, groups, settings):
    """
    بدء حملة نشر لحساب واحد.
    """
    delay = int(settings.get('message_delay', 10))
    is_force_all = settings.get('is_force_all', False)
    
    groups_to_publish = []
    if is_force_all:
        try:
            # نستخدم run_with_safe_clone لجلب المجموعات بأمان
            groups_to_publish = await run_with_safe_clone(f"web_session_{phone}", get_account_groups)
        except Exception as e:
            logging.error(f"Failed to fetch groups for {phone} for 'Force All' campaign: {e}")
            return
    else:
        groups_to_publish = groups

    if not groups_to_publish:
        logging.warning(f"No groups to publish to for account {phone}. Campaign will not run.")
        return

    logging.info(f"Starting campaign for {phone} on {len(groups_to_publish)} groups.")

    for group_target in groups_to_publish:
        message = random.choice(messages)
        try:
            await run_with_safe_clone(f"web_session_{phone}", lambda client: client.send_message(group_target, message))
            logging.info(f"Message sent to '{group_target}' from {phone}")
        except Exception as e:
            logging.error(f"Failed to send to '{group_target}' from {phone}: {e}")
        
        await asyncio.sleep(delay)
    
    logging.info(f"Campaign finished for account {phone}.")

async def get_account_groups(client):
    """
    جلب قائمة بمعرفات جميع المجموعات والقنوات الصالحة للنشر للحساب.
    """
    dialogs = await client.get_dialogs()
    valid_groups = []
    for d in dialogs:
        if d.is_group or d.is_channel:
            valid_groups.append(d.id)
    return valid_groups

