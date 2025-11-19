# main.py
import os
import asyncio
import logging
import tempfile
import sqlite3
import importlib.metadata
from typing import Optional, Tuple, Any, Dict, List

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityStrike, 
    MessageEntityUnderline, MessageEntitySpoiler, MessageEntityCode, 
    MessageEntityPre, MessageEntityTextUrl, MessageEntityBlockquote,
    MessageEntityUrl, MessageEntityMention, MessageEntityEmail
)

import rubpy
from rubpy.bot import BotClient
from rubpy.bot.exceptions import APIException
from rubpy.enums import ParseMode

# ----------------- logging -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-to-rubika")

# ----------------- env -----------------
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
RUBIKA_BOT_AUTH = os.environ.get("RUBIKA_BOT_AUTH")

TG_CHANNEL_1 = os.environ.get("TG_CHANNEL_1")
TG_CHANNEL_2 = os.environ.get("TG_CHANNEL_2")

RUBIKA_CHANNEL_1 = os.environ.get("RUBIKA_CHANNEL_1")
RUBIKA_CHANNEL_2 = os.environ.get("RUBIKA_CHANNEL_2")

PORT = int(os.environ.get("PORT", 8080))
DB_PATH = os.environ.get("MAPPING_DB_PATH", "mappings.db")

required = [
    "API_ID", "API_HASH", "SESSION_STRING",
    "RUBIKA_BOT_AUTH", "TG_CHANNEL_1", "TG_CHANNEL_2",
    "RUBIKA_CHANNEL_1", "RUBIKA_CHANNEL_2"
]
for r in required:
    if not os.environ.get(r):
        raise SystemExit(f"Missing required env var: {r}")

# ----------------- mapping -----------------
MAP = {
    str(int(TG_CHANNEL_1)): RUBIKA_CHANNEL_1,
    str(int(TG_CHANNEL_2)): RUBIKA_CHANNEL_2,
}

# ----------------- clients -----------------
tg_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
rb = BotClient(token=RUBIKA_BOT_AUTH)


# ----------------- DB helpers -----------------
def init_db(path: str = DB_PATH):
    conn = sqlite3.connect(path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mappings (
            tg_chat_id TEXT NOT NULL,
            tg_message_id INTEGER NOT NULL,
            rubika_chat_id TEXT NOT NULL,
            rubika_message_id TEXT NOT NULL,
            PRIMARY KEY (tg_chat_id, tg_message_id)
        )"""
    )
    conn.commit()
    return conn


DB_CONN = init_db()


def save_mapping(tg_chat_id: str, tg_message_id: int, rubika_chat_id: str, rubika_message_id: str):
    cur = DB_CONN.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO mappings (tg_chat_id, tg_message_id, rubika_chat_id, rubika_message_id) VALUES (?, ?, ?, ?)",
        (tg_chat_id, int(tg_message_id), rubika_chat_id, str(rubika_message_id)),
    )
    DB_CONN.commit()


def get_mapping(tg_chat_id: str, tg_message_id: int) -> Optional[Tuple[str, str]]:
    cur = DB_CONN.cursor()
    cur.execute(
        "SELECT rubika_chat_id, rubika_message_id FROM mappings WHERE tg_chat_id = ? AND tg_message_id = ?",
        (tg_chat_id, int(tg_message_id)),
    )
    row = cur.fetchone()
    if row:
        return row[0], row[1]
    return None


def delete_mapping(tg_chat_id: str, tg_message_id: int):
    cur = DB_CONN.cursor()
    cur.execute(
        "DELETE FROM mappings WHERE tg_chat_id = ? AND tg_message_id = ?",
        (tg_chat_id, int(tg_message_id)),
    )
    DB_CONN.commit()


# ----------------- utilities -----------------
def _extract_message_id(result: Any) -> Optional[str]:
    if result is None:
        return None
    
    for attr in ("message_id", "id", "msg_id"):
        if hasattr(result, attr):
            return str(getattr(result, attr))
    try:
        if isinstance(result, dict):
            if 'data' in result and isinstance(result['data'], dict):
                 if 'message_update' in result['data']:
                     return str(result['data']['message_update'].get('message_id'))
                 if 'message_id' in result['data']:
                     return str(result['data']['message_id'])

            for key in ("message_id", "id", "msg_id"):
                if key in result:
                    return str(result[key])
    except Exception:
        pass
    try:
        return str(result)
    except Exception:
        return None


def guess_file_type_from_telethon(msg) -> str:
    if getattr(msg, "photo", None):
        return "Image"
    if getattr(msg, "video", None):
        return "Video"
    if getattr(msg, "voice", None) or getattr(msg, "voice_note", None):
        return "Voice"
    if getattr(msg, "gif", None) or getattr(msg, "animation", None):
        return "Gif"
    return "File"


# --- تابع تبدیل متن و Entityها به فرمت Markdown ---
def apply_markdown_to_text(text: str, entities: list) -> str:
    """
    این تابع متن خام و لیست فرمت‌های تلگرام را می‌گیرد و
    علامت‌های مارک‌داون (**، __، -- و ...) را به متن اضافه می‌کند.
    """
    if not entities or not text:
        return text
    
    # لیستی از نقاطی که باید علامت درج شود: (موقعیت، علامت)
    insertions = []
    for ent in entities:
        start = ent.offset
        end = ent.offset + ent.length
        
        # فقط فرمت‌هایی که روبیکا پشتیبانی می‌کند
        if isinstance(ent, MessageEntityBold):
            insertions.append((start, "**"))
            insertions.append((end, "**"))
        elif isinstance(ent, MessageEntityItalic):
            insertions.append((start, "__"))
            insertions.append((end, "__"))
        elif isinstance(ent, MessageEntityStrike):
            insertions.append((start, "~~"))
            insertions.append((end, "~~"))
        elif isinstance(ent, MessageEntityUnderline):
            # اضافه شدن پشتیبانی از زیرخط (Underline) با استفاده از --
            insertions.append((start, "--"))
            insertions.append((end, "--"))
        elif isinstance(ent, MessageEntitySpoiler):
            insertions.append((start, "||"))
            insertions.append((end, "||"))
        elif isinstance(ent, (MessageEntityCode, MessageEntityPre)):
            insertions.append((start, "`"))
            insertions.append((end, "`"))
        elif isinstance(ent, MessageEntityTextUrl):
            # برای لینک: [متن](لینک)
            insertions.append((start, "["))
            insertions.append((end, f"]({ent.url})"))
        elif isinstance(ent, MessageEntityBlockquote):
             # برای نقل قول
             insertions.append((start, "> "))
    
    # مرتب‌سازی نزولی (از آخر به اول) برای جلوگیری از بهم ریختن ایندکس‌ها
    insertions.sort(key=lambda x: x[0], reverse=True)
    
    res_text = text
    for index, string_to_insert in insertions:
        if 0 <= index <= len(res_text):
            res_text = res_text[:index] + string_to_insert + res_text[index:]
            
    return res_text


async def try_send_file_with_fallback(rubika_chat_id: str, local_path: str, caption: str, primary_type: str):
    try:
        # ارسال با parse_mode='Markdown'
        res = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type=primary_type, text=caption, parse_mode=ParseMode.MARKDOWN)
        return _extract_message_id(res)
    except APIException as e:
        msg = getattr(e, "message", str(e))
        logger.warning("send_file primary type %s failed: %s. Trying fallback to 'File'...", primary_type, msg)
        try:
            file_name = os.path.basename(local_path)
            # فال‌بک هم با مارک‌داون
            res2 = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type="File", text=caption, file_name=file_name, parse_mode=ParseMode.MARKDOWN)
            return _extract_message_id(res2)
        except Exception as e2:
            logger.exception("Fallback send_file(File) also failed: %s", e2)
            raise


async def forward_to_rubika_and_store(tg_chat_id: str, tg_message_id: int, rubika_chat_id: str, text: str = None, file_path: str = None, caption: str = None, file_type: str = "File"):
    try:
        if file_path:
            logger.info("Uploading %s to Rubika channel %s ...", file_type, rubika_chat_id)
            rub_mid = await try_send_file_with_fallback(rubika_chat_id, file_path, caption, file_type)
        else:
            logger.info("Sending text to Rubika channel %s", rubika_chat_id)
            res = await rb.send_message(chat_id=rubika_chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
            rub_mid = _extract_message_id(res)

        if rub_mid:
            save_mapping(tg_chat_id, tg_message_id, rubika_chat_id, rub_mid)
            logger.info("Saved mapping: TG %s/%s -> Rubika %s/%s", tg_chat_id, tg_message_id, rubika_chat_id, rub_mid)
        else:
            logger.warning("No rubika message id returned for TG %s/%s", tg_chat_id, tg_message_id)
        return rub_mid
    except Exception as e:
        logger.exception("Failed to forward to rubika for tg %s/%s: %s", tg_chat_id, tg_message_id, e)
        return None


# ----------------- Telethon handlers -----------------
@tg_client.on(events.NewMessage(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def new_message_handler(event):
    try:
        msg = event.message
        tg_chat_id = str(event.chat_id)
        rubika_target = MAP.get(tg_chat_id)
        if not rubika_target:
            logger.warning("No mapping for tg chat %s", tg_chat_id)
            return

        # تبدیل متن به فرمت مارک‌داون
        markdown_text = apply_markdown_to_text(msg.message, msg.entities)
        
        if msg.message and not msg.media:
            await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, text=markdown_text)
            return

        if msg.media:
            tmpdir = tempfile.mkdtemp()
            try:
                file_path = await msg.download_media(file=tmpdir)
                caption = apply_markdown_to_text(msg.message or "", msg.entities) or None
                
                ftype = guess_file_type_from_telethon(msg)
                if ftype == "Voice" and not os.path.splitext(file_path)[1]:
                    new_path = file_path + ".ogg"
                    os.rename(file_path, new_path)
                    file_path = new_path
                
                await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, file_path=file_path, caption=caption, file_type=ftype)
            finally:
                try:
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass
            return
    except Exception as e:
        logger.exception("Error in new_message_handler: %s", e)


@tg_client.on(events.MessageEdited(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def edited_message_handler(event):
    try:
        msg = event.message
        tg_chat_id = str(event.chat_id)
        mapping = get_mapping(tg_chat_id, msg.id)
        if not mapping:
            logger.info("Edited message mapping not found for %s/%s — ignoring", tg_chat_id, msg.id)
            return
        rubika_chat_id, rubika_msg_id = mapping
        
        new_markdown_text = apply_markdown_to_text(msg.message or "", msg.entities)

        if new_markdown_text:
            logger.info("Editing Rubika message %s in chat %s", rubika_msg_id, rubika_chat_id)
            try:
                await rb.edit_message_text(chat_id=rubika_chat_id, message_id=rubika_msg_id, text=new_markdown_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.exception("Failed to edit rubika message: %s", e)
    except Exception as e:
        logger.exception("Error in edited_message_handler: %s", e)


@tg_client.on(events.MessageDeleted(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def deleted_message_handler(event):
    try:
        deleted_ids = event.deleted_ids
        tg_chat_id = str(event.chat_id)
        for mid in deleted_ids:
            mapping = get_mapping(tg_chat_id, mid)
            if not mapping:
                logger.info("Deleted message mapping not found for %s/%s — ignoring", tg_chat_id, mid)
                continue
            rubika_chat_id, rubika_msg_id = mapping
            logger.info("Deleting rubika message %s from chat %s (origin tg %s/%s)", rubika_msg_id, rubika_chat_id, tg_chat_id, mid)
            try:
                await rb.delete_message(chat_id=rubika_chat_id, message_id=rubika_msg_id)
                delete_mapping(tg_chat_id, mid)
            except Exception as e:
                logger.exception("Failed to delete rubika message: %s", e)
    except Exception as e:
        logger.exception("Error in deleted_message_handler: %s", e)


# ----------------- startup / health -----------------
async def start_services():
    try:
        version = importlib.metadata.version("rubpy")
        logger.info(f"Starting rubpy client (Version: {version})...")
    except:
        logger.info("Starting rubpy client (Unknown Version)...")
        
    await rb.start()

    logger.info("Starting Telethon client...")
    await tg_client.start()

    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    app.add_routes([web.get("/health", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Health endpoint started on port %s", PORT)

    logger.info("Running until disconnected...")
    await tg_client.run_until_disconnected()


def main():
    try:
        asyncio.run(start_services())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        try:
            asyncio.run(rb.close())
        except Exception:
            pass


if __name__ == "__main__":
    main()
