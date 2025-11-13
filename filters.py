# -*- coding: utf-8 -*-
"""
filters.py - Blueprint لعمليات التصفية والفحص والخروج من القنوات
"""

import asyncio
import logging
import random
from flask import Blueprint, request
from telethon import errors, types
from telethon.tl.functions.channels import LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.types import ChannelParticipantsBots, PeerUser
from telethon.errors import ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError
from sessions import run_with_safe_clone, load_session_config_by_name
from utils import format_response, run_in_new_loop

filters_bp = Blueprint('filters', __name__)

# ============================================================
# 🧠 دوال تحليل الفحص العميق
# ============================================================

async def analyze_group_post_permission(client, entity):
    """
    تحليل ذكي ومحسّن لمعرفة صلاحيات النشر في مجموعة أو قناة.
    يُرجع قاموسًا يحتوي على `status` و `reason`.
    """
    try:
        # حقوق النشر الأساسية
        if hasattr(entity, 'banned_rights') and entity.banned_rights and entity.banned_rights.send_messages:
            return {"status": "muted", "reason": "أنت مكتوم في هذه المجموعة."}

        # إذا كان الحساب محظورًا بالكامل
        if hasattr(entity, 'banned_rights') and entity.banned_rights and entity.banned_rights.view_messages:
            return {"status": "banned", "reason": "تم حظر الحساب من هذه المجموعة."}

        # فحص أعمق باستخدام GetFullChannelRequest
        full = await client(GetFullChannelRequest(entity))
        
        # التأكد مرة أخرى من حقوق الإرسال بعد جلب البيانات الكاملة
        if hasattr(full.full_chat, 'banned_rights') and full.full_chat.banned_rights and full.full_chat.banned_rights.send_messages:
            return {"status": "muted", "reason": "أنت مكتوم في هذه المجموعة."}
            
        # إذا كانت قناة وليست مجموعة (للنشر فقط)
        if isinstance(entity, types.Channel) and not entity.megagroup and entity.broadcast:
             if not entity.creator and not getattr(entity.admin_rights, 'post_messages', False):
                 return {"status": "read_only", "reason": "هذه قناة نشر، والمشرفون فقط يمكنهم الإرسال."}

        # حالة المجموعات المرتبطة بقنوات (للنقاش فقط)
        if hasattr(full.full_chat, "linked_chat_id") and full.full_chat.linked_chat_id:
             return {"status": "linked_only", "reason": "هذه مجموعة نقاش مرتبطة بقناة، قد تكون مقيدة."}

        # إذا كان كل شيء على ما يرام
        return {"status": "ok", "reason": "يمكن النشر في هذه المجموعة/القناة."}
        
    except (ChatWriteForbiddenError, UserBannedInChannelError):
        # خطأ صريح من تيليجرام يفيد بالمنع أو الحظر
        return {"status": "banned", "reason": "أنت محظور من الكتابة في هذه المجموعة/القناة."}
    except ChannelPrivateError:
        return {"status": "private", "reason": "هذه قناة خاصة ولا يمكن الوصول إليها."}
    except Exception as e:
        # التعامل مع أخطاء أخرى قد تشير إلى الحظر
        if "forbidden" in str(e).lower() or "banned" in str(e).lower():
            return {"status": "banned", "reason": str(e)}
        # إذا كان الخطأ غير معروف، نعيده كما هو
        logging.warning(f"Unknown status for entity {getattr(entity, 'id', '')}: {e}")
        return {"status": "unknown", "reason": f"فشل التحقق: {e}"}


async def deep_scan_channels(phone_number: str):
    """
    Performs a deep scan of channels for a given phone number.
    """
    base_name = f"web_session_{phone_number}"
    async def scan_task(client):
        dialogs = await client.get_dialogs()
        results = []
        
        summary = {
            "total": 0, "with_bots": 0, "muted": 0, 
            "banned": 0, "can_post": 0
        }

        for dialog in dialogs:
            entity = dialog.entity
            if isinstance(entity, PeerUser) or not hasattr(entity, "title"):
                continue

            summary["total"] += 1
            entity_type = 'group'
            if isinstance(entity, types.Channel) and not entity.megagroup:
                entity_type = 'channel'

            bots = []
            try:
                participants = await client.get_participants(entity, limit=100, filter=ChannelParticipantsBots)
                bots = [p.username for p in participants if p.username]
            except Exception:
                pass

            permission_info = await analyze_group_post_permission(client, entity)
            status = permission_info["status"]
            reason = permission_info["reason"]

            if status == "muted": summary["muted"] += 1
            elif status == "banned": summary["banned"] += 1
            elif status == "ok": summary["can_post"] += 1
            if len(bots) > 0: summary["with_bots"] += 1

            invite_link = ""
            try:
                if hasattr(entity, "username") and entity.username:
                    invite_link = f"https://t.me/{entity.username}"
            except Exception:
                pass

            results.append({
                "name": getattr(entity, "title", "Unknown"),
                "id": entity.id,
                "invite_link": invite_link,
                "status": status,
                "reason": reason,
                "has_bots": len(bots) > 0,
                "bots_count": len(bots),
                "type": entity_type,
            })
        
        # To avoid double counting blocked in muted
        summary["banned"] = summary.get("banned", 0)

        return {"account": phone_number, "groups": results, "summary": summary}
    
    try:
        return await run_with_safe_clone(base_name, scan_task)
    except FileNotFoundError:
        return {"account": phone_number, "error": "session_not_found", "groups": []}
    except PermissionError:
        return {"account": phone_number, "error": "session_not_ready", "groups": []}
    except Exception as e:
        logging.error(f"Error scanning channels for {phone_number}: {e}")
        return {"account": phone_number, "error": str(e), "groups": []}


# ============================================================
# 🚪 مسارات الخروج من القنوات والمجموعات
# ============================================================

@filters_bp.route('/leave-group-safe', methods=['POST'])
def leave_group_safe_route():
    data = request.json
    phone = data.get('account')
    group_id = data.get('group_id')

    if not phone or not group_id:
        return format_response(success=False, error="Account and group_id are required.", code=400)

    return run_in_new_loop(leave_group_task(phone, group_id))

@filters_bp.route('/join-group-safe', methods=['POST'])
def join_group_safe_route():
    data = request.json
    phone = data.get('account')
    group_id = data.get('group_id')

    if not phone or not group_id:
        return format_response(success=False, error="Account and group_id are required.", code=400)

    base_name = f"web_session_{phone}"
    async def join_action(client):
        from telethon.tl.functions.channels import JoinChannelRequest
        try:
            await client(JoinChannelRequest(group_id))
            return {"status": "success"}
        except errors.UserAlreadyParticipantError:
            return {"status": "skipped", "reason": "Already a member"}
        except Exception as e:
            logging.error(f"Failed to join group {group_id} for {phone}: {e}")
            raise e

    return run_in_new_loop(run_with_safe_clone(base_name, join_action))


async def leave_group_task(phone, group_id):
    """
    مهمة الخروج من مجموعة أو قناة واحدة.
    """
    base_name = f"web_session_{phone}"
    async def leave_action(client):
        try:
            # محاولة تحويل group_id إلى كيان
            entity = await client.get_entity(group_id)
            await client(LeaveChannelRequest(entity))
            return {"status": "success"}
        except (ValueError, TypeError):
             # إذا كان رقمًا صحيحًا، يمكن استخدامه مباشرة
            await client(LeaveChannelRequest(int(group_id)))
            return {"status": "success"}
        except errors.FloodWaitError as e:
            logging.warning(f"Flood wait of {e.seconds}s on leave for {phone}")
            return {"status": "flood_wait", "retry_after": e.seconds}
        except Exception as e:
            logging.error(f"Failed to leave group {group_id} for {phone}: {e}")
            raise e

    try:
        result = await run_with_safe_clone(base_name, leave_action)
        return format_response(data=result)
    except Exception as e:
        return format_response(success=False, error=str(e), code=500)
