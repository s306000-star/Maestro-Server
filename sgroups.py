# -*- coding: utf-8 -*-
"""
sgroups.py – Smart Group & Channel Analyzer
--------------------------------------------
✅ يقوم بفحص كل القنوات والمجموعات في الحساب المحدد
✅ يرسل رسالة اختبار إلى المجموعات القابلة للنشر فقط
✅ يغادر جميع القنوات بدون استثناء
✅ يغادر المجموعات التي لا يمكن النشر بها (محظورة / مقيدة / مغلقة)
"""

from flask import Blueprint, request
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import GetFullChannelRequest, LeaveChannelRequest
from telethon.tl.types import ChannelParticipantsBots, PeerUser
import asyncio, logging
from config import CONFIG
from sessions import load_session_config_by_name, run_with_safe_clone
from utils import format_response, run_in_new_loop

sgroups_bp = Blueprint("sgroups", __name__)

# ======================================================
# 🧩 فحص صلاحيات النشر داخل كيان (مجموعة أو قناة)
# ======================================================
async def test_post_permission(client, entity, test_message="🔷 Test message (auto-check)"):
    try:
        msg = await client.send_message(entity, test_message)
        return {"can_post": True, "reason": "✅ Can post message"}
    except errors.ChatWriteForbiddenError:
        return {"can_post": False, "reason": "🚫 Write forbidden in this chat"}
    except errors.UserBannedInChannelError:
        return {"can_post": False, "reason": "⛔ User banned in this channel"}
    except errors.FloodWaitError as fw:
        await asyncio.sleep(fw.seconds + 1)
        return {"can_post": False, "reason": f"⏳ Flood wait for {fw.seconds}s"}
    except Exception as e:
        return {"can_post": False, "reason": f"❌ Exception: {e}"}


# ======================================================
# 🧠 تحليل ذكي للمجموعة أو القناة
# ======================================================
async def analyze_group(client, entity, test_message="🔷 Test", auto_leave=False, leave_log=None):
    """
    - يجرب إرسال رسالة للمجموعات فقط التي يمكن النشر بها.
    - يغادر جميع القنوات.
    - يغادر المجموعات التي لا يمكن النشر بها.
    """
    status = "ok"
    reason = "✅ Message test passed"
    can_post = True

    try:
        # تجاهل المستخدمين
        if isinstance(entity, PeerUser):
            return None

        # تحديد نوع الكيان
        full = await client(GetFullChannelRequest(entity))
        entity_type = "channel" if getattr(entity, "broadcast", False) else "group"

        # فحص صلاحيات النشر
        probe = await test_post_permission(client, entity, test_message)
        can_post = probe["can_post"]
        reason = probe["reason"]

        # 💬 إرسال فعلي فقط للمجموعات القابلة للنشر
        if entity_type == "group" and can_post:
            try:
                await client.send_message(entity, test_message)
                reason = "✅ Test message sent successfully to group"
            except Exception as e:
                can_post = False
                status = "error"
                reason = f"❌ Failed to send message: {e}"

        # 🚪 الخروج الذكي
        if auto_leave:
            # 1️⃣ يغادر جميع القنوات بدون استثناء
            if entity_type == "channel":
                try:
                    await client(LeaveChannelRequest(entity))
                    if leave_log is not None:
                        leave_log.append({
                            "id": entity.id,
                            "name": getattr(entity, "title", "Unknown"),
                            "reason": "🧹 Auto-left (channel cleanup)"
                        })
                except Exception as e:
                    logging.warning(f"⚠️ Failed to leave channel {entity.id}: {e}")

            # 2️⃣ يغادر المجموعات التي لا يمكن النشر بها
            elif entity_type == "group" and not can_post:
                try:
                    await client(LeaveChannelRequest(entity))
                    if leave_log is not None:
                        leave_log.append({
                            "id": entity.id,
                            "name": getattr(entity, "title", "Unknown"),
                            "reason": reason
                        })
                except Exception as e:
                    logging.warning(f"⚠️ Failed to leave group {entity.id}: {e}")

        # الحالة النهائية
        status = "ok" if can_post else "restricted"
        return {
            "id": entity.id,
            "name": getattr(entity, "title", "Unknown"),
            "type": entity_type,
            "status": status,
            "reason": reason,
            "can_post": can_post,
        }

    except Exception as e:
        return {
            "id": getattr(entity, "id", 0),
            "name": getattr(entity, "title", "Unknown"),
            "status": "error",
            "reason": f"Exception: {e}",
            "can_post": False
        }


# ======================================================
# 📊 فحص كل القنوات والمجموعات
# ======================================================
async def scan_all_groups(client, test_message="🔷 Test", auto_leave=False):
    dialogs = await client.get_dialogs(limit=None)
    groups = []
    leave_log = []
    sem = asyncio.Semaphore(5)

    async def worker(dialog):
        async with sem:
            e = dialog.entity
            if isinstance(e, PeerUser):
                return  # تجاهل المستخدمين تمامًا
            try:
                info = await analyze_group(client, e, test_message=test_message, auto_leave=auto_leave, leave_log=leave_log)
                if info:
                    groups.append(info)
            except Exception as ex:
                groups.append({
                    "name": getattr(e, "title", "Unknown"),
                    "status": "error",
                    "reason": str(ex)
                })

    await asyncio.gather(*[worker(d) for d in dialogs])
    return {"groups": groups, "left_log": leave_log}


# ======================================================
# 🚀 المهمة الرئيسية الخاصة بالفحص
# ======================================================
async def scan_groups_task(session_name, test_message, auto_leave):
    try:
        base_name = session_name.replace('.session', '').replace('web_session_', '').strip()
        final_base_name = f"web_session_{base_name}"

        async def work(client):
            result_data = await scan_all_groups(client, test_message=test_message, auto_leave=auto_leave)
            summary = {}
            for g in result_data["groups"]:
                status = g.get("status", "unknown")
                summary[status] = summary.get(status, 0) + 1
            summary["total"] = len(result_data["groups"])
            return {"summary": summary, "groups": result_data["groups"], "left_log": result_data["left_log"]}

        result = await run_with_safe_clone(final_base_name, work)
        return format_response(data=result)

    except FileNotFoundError:
        return format_response(success=False, error="Session file or config not found.", code=404)
    except PermissionError:
        return format_response(success=False, error="Session not authorized. Please re-authenticate.", code=403)
    except Exception as e:
        logging.exception("scan-groups task failed")
        return format_response(success=False, error=str(e), code=500)


# ======================================================
# 🌐 مسار API الرئيسي
# ======================================================
@sgroups_bp.route("/scan-groups", methods=["POST"])
def scan_groups_route():
    data = request.get_json(silent=True) or {}
    session_name = data.get("session_name")
    if not session_name:
        return format_response(success=False, error="Missing session_name", code=400)

    test_message = data.get("test_message", "🔷 Test message (auto-check)")
    auto_leave = data.get("auto_leave_on_fail", False)

    return run_in_new_loop(scan_groups_task(session_name, test_message, auto_leave))