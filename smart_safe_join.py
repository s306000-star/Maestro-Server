# -*- coding: utf-8 -*-
"""
smart_safe_join.py — Smart-Safe Join Engine v5
---------------------------------------------
✔️ يدعم جميع أنواع روابط التليجرام
✔️ فحص مسبق (Pre-Validation)
✔️ وضعان: Smart و Safe
✔️ يمنع الانضمام إلى القنوات (Channels) في الوضع الذكي Smart Join
✔️ تقارير مفصلة + حماية ضد FloodWait
"""

from flask import Blueprint, request, jsonify
from telethon import errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.errors import (
    UserAlreadyParticipantError, InviteRequestSentError, ChannelsTooMuchError,
    ChannelPrivateError, InviteHashExpiredError, InviteHashInvalidError,
    FloodWaitError, RPCError
)
import asyncio, re, random, logging
from typing import List, Dict, Any, Tuple
from config import CONFIG
from sessions import run_with_safe_clone, load_session_config_by_name
from utils import format_response, run_in_new_loop

smart_join_bp = Blueprint("smart_join", __name__)

# =========================
# 🧩 أدوات مساعدة
# =========================
_LINK_RE = re.compile(r"(?:https?://)?t\.me/(?:\+|joinchat/)?([A-Za-z0-9_+-]+)|(?:@)([A-Za-z0-9_]+)", re.IGNORECASE)

def _normalize_links(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        pool = raw
    else:
        # This part handles extracting links from a raw text block
        text_links = re.findall(r'https?://t\.me/[^\s]+', str(raw))
        at_mentions = re.findall(r'@([a-zA-Z0-9_]{5,})', str(raw))
        pool = text_links + at_mentions
        
    seen, uniq = set(), []
    for x in pool:
        x = x.strip().replace(" ", "")
        if x and x not in seen:
            # Further normalization for user convenience
            if 't.me/+' in x:
                x = x.split('t.me/+')[-1]
            elif 't.me/joinchat/' in x:
                x = x.split('t.me/joinchat/')[-1]
            elif 't.me/' in x:
                x = x.split('t.me/')[-1]

            if x not in seen:
                seen.add(x)
                uniq.append(x)
    return uniq

def _classify_link(token: str) -> Tuple[str, str]:
    if token.startswith("+") or "joinchat" in token or len(token) >= 16 and not token.isalnum():
        return ("invite_hash", token.replace("+", "").replace("joinchat/", ""))
    return ("username", token.lstrip("@"))

# =========================
# 🧠 فحص مسبق للرابط
# =========================
async def _validate_invite(client, kind: str, value: str) -> Dict[str, Any]:
    if kind != "invite_hash":
        return {"ok": True, "type": "public"}
    try:
        info = await client(CheckChatInviteRequest(value))
        title = getattr(info, "chat", None)
        return {"ok": True, "type": "private", "title": getattr(title, "title", None)}
    except InviteHashExpiredError:
        return {"ok": False, "error": "invite_hash_expired"}
    except InviteHashInvalidError:
        return {"ok": False, "error": "invite_hash_invalid"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================
# 🚀 انضمام فعلي
# =========================
async def _join_single(client, kind: str, value: str, ignore_channels: bool) -> Dict[str, Any]:
    try:
        if kind == "invite_hash":
            # For invite hashes, we must check the type after joining.
            updates = await client(ImportChatInviteRequest(value))
            chat = updates.chats[0]
            if ignore_channels and getattr(chat, "broadcast", False):
                # We joined, but we must leave now.
                await client(JoinChannelRequest(chat)) # This is how you leave a broadcast channel
                return {"status": "skipped_channel", "error": "channel_skipped"}
            return {"status": "joined", "via": "invite_hash"}
        else: # username
            entity = await client.get_entity(value)
            if ignore_channels and getattr(entity, "broadcast", False):
                return {"status": "skipped_channel", "error": "channel_skipped"}
            await client(JoinChannelRequest(entity))
            return {"status": "joined", "via": "username"}
    except UserAlreadyParticipantError:
        return {"status": "already", "error": "already_participant"}
    except InviteRequestSentError:
        return {"status": "pending", "error": "invite_request_sent"}
    except ChannelsTooMuchError:
        return {"status": "failed", "error": "channels_too_much"}
    except InviteHashExpiredError:
        return {"status": "failed", "error": "invite_hash_expired"}
    except InviteHashInvalidError:
        return {"status": "failed", "error": "invite_hash_invalid"}
    except ChannelPrivateError:
        return {"status": "failed", "error": "channel_private"}
    except FloodWaitError as fw:
        return {"status": "retry", "error": f"flood_wait_{fw.seconds}", "retry_after": fw.seconds}
    except RPCError as rpc:
        return {"status": "failed", "error": f"rpc_error:{type(rpc).__name__}"}
    except Exception as e:
        # Catch common errors like "No user has..."
        if "No user has" in str(e) or "Cannot find any entity" in str(e):
            return {"status": "failed", "error": "username_invalid"}
        return {"status": "failed", "error": str(e)}

# =========================
# 🤖 المنطق الذكي / الآمن
# =========================
async def _smart_join_flow(client, links: List[str], options: Dict[str, Any]):
    mode = options.get("mode", "smart")
    ignore_channels = options.get("ignore_channels", True)
    
    # Default settings
    delay_min, delay_max, concurrency, max_retries = 2.0, 5.0, 2, 2
    if mode == "safe":
        delay_min, delay_max, concurrency, max_retries = 5.0, 9.0, 1, 1

    sem = asyncio.Semaphore(concurrency)
    results, joined, failed, retried, already, pending, skipped_channels = [], 0, 0, 0, 0, 0, 0

    async def worker(token):
        nonlocal joined, failed, retried, already, pending, skipped_channels
        async with sem:
            kind, value = _classify_link(token)
            
            # Pre-validation (for private links)
            if kind == "invite_hash":
                pre = await _validate_invite(client, kind, value)
                if not pre.get("ok"):
                    results.append({"link": token, "result": {"status": "invalid", "error": pre.get("error")}})
                    failed += 1
                    return

            attempt, last_result = 0, None
            while attempt < max_retries:
                attempt += 1
                last_result = await _join_single(client, kind, value, ignore_channels if mode == "smart" else False)
                status = last_result.get("status")

                if status == "retry":
                    retried += 1
                    wait = last_result.get("retry_after", 10) + (5 if mode == "safe" else 2)
                    logging.warning(f"FloodWait on {token}, sleeping for {wait}s.")
                    await asyncio.sleep(wait)
                    continue # Retry the same link
                else:
                    break # Exit retry loop for this link
            
            # Final status processing
            status = last_result.get("status")
            if status == "joined": joined += 1
            elif status == "pending": pending += 1
            elif status == "already": already += 1
            elif status == "skipped_channel": skipped_channels += 1
            else: failed += 1
            
            results.append({"link": token, "result": last_result})
            await asyncio.sleep(random.uniform(delay_min, delay_max))

    await asyncio.gather(*[worker(l) for l in links])

    summary = {
        "total": len(links), "joined": joined, "pending": pending,
        "already": already, "failed": failed, "retried": retried,
        "skipped_channels": skipped_channels
    }
    return {"summary": summary, "details": results}

# =========================
# 🧵 مهمة Async رئيسية
# =========================
async def _join_task(session_name, links_raw, options):
    links = _normalize_links(links_raw)
    if not links:
        return format_response(success=False, error="NO_LINKS", code=400)

    async def core_task(client):
        return await _smart_join_flow(client, links, options)

    # run_with_safe_clone handles client creation, connection, and cleanup
    result = await run_with_safe_clone(session_name, core_task)
    return {"ok": True, "data": result}

# =========================
# 🧠 REST APIs
# =========================
@smart_join_bp.route("/join/smart", methods=["POST"])
def api_join_smart():
    payload = request.get_json(silent=True) or {}
    session_name = payload.get("session_name")
    
    if not session_name:
        return format_response(success=False, error="Missing session_name", code=400)
    
    # Ensure session_name has the 'web_session_' prefix if not provided
    if not session_name.startswith("web_session_"):
        session_name = f"web_session_{session_name}"

    config = load_session_config_by_name(session_name)
    if not config:
        return format_response(success=False, error=f"Session config for '{session_name}' not found", code=404)

    options = payload.get("options", {})
    links_raw = payload.get("links") or payload.get("text") or ""
    
    # We use run_in_new_loop to handle the async task from a sync Flask route
    return run_in_new_loop(_join_task(session_name, links_raw, options))

