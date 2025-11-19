# main.py
import os
import asyncio
import logging
import tempfile
import sqlite3
from typing import Optional, Tuple, Any, Dict, List

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
# ایمپورت کردن تایپ‌های فرمت‌دهی تلگرام برای شناسایی
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityStrike, 
    MessageEntityUnderline, MessageEntitySpoiler, MessageEntityCode, 
    MessageEntityPre, MessageEntityTextUrl, MessageEntityBlockquote
)

from rubpy.bot import BotClient
from rubpy.bot.exceptions import APIException

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


# --- تابع تبدیل مستقیم Entity تلگرام به Metadata روبیکا ---
def telethon_to_metadata(entities: list) -> Optional[Dict]:
    """
    Converts Telethon entities directly to Rubika metadata structure.
    Rubika expects: {'meta_data_parts': [{'from_index': int, 'length': int, 'type': str, ...}]}
    """
    if not entities:
        return None

    parts = []
    for entity in entities:
        part_type = None
        extra_data = {}

        # نگاشت (Mapping) انواع فرمت‌های تلگرام به روبیکا
        if isinstance(entity, MessageEntityBold):
            part_type = "Bold"
        elif isinstance(entity, MessageEntityItalic):
            part_type = "Italic"
        elif isinstance(entity, MessageEntityStrike):
            part_type = "Strike"
        elif isinstance(entity, MessageEntityUnderline):
            part_type = "Underline"
        elif isinstance(entity, MessageEntitySpoiler):
            part_type = "Spoiler"
        elif isinstance(entity, (MessageEntityCode, MessageEntityPre)):
            part_type = "Mono"
        elif isinstance(entity, MessageEntityTextUrl):
            part_type = "Link"
            extra_data["link"] = {"type": "web", "url": entity.url}
        # نقل‌قول (Quote) در روبیکا متادیتای استاندارد ندارد، معمولاً به صورت متن > نمایش داده می‌شود
        # اما اگر نیاز باشد می‌توان آن را به عنوان Mono یا فرمت دیگر در نظر گرفت. فعلاً نادیده می‌گیریم.

        if part_type:
            data = {
                "from_index": entity.offset,
                "length": entity.length,
                "type": part_type
            }
            if extra_data:
                data.update(extra_data)
            parts.append(data)
    
    if not parts:
        return None
        
    return {"meta_data_parts": parts}


async def try_send_file_with_fallback(rubika_chat_id: str, local_path: str, caption: str, primary_type: str, metadata: dict = None):
    try:
        # استفاده از metadata به جای parse_mode
        res = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type=primary_type, text=caption, metadata=metadata)
        return _extract_message_id(res)
    except APIException as e:
        msg = getattr(e, "message", str(e))
        logger.warning("send_file primary type %s failed: %s. Trying fallback to 'File'...", primary_type, msg)
        try:
            file_name = os.path.basename(local_path)
            # فال‌بک به فایل معمولی با همان متادیتا
            res2 = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type="File", text=caption, file_name=file_name, metadata=metadata)
            return _extract_message_id(res2)
        except Exception as e2:
            logger.exception("Fallback send_file(File) also failed: %s", e2)
            raise


async def forward_to_rubika_and_store(tg_chat_id: str, tg_message_id: int, rubika_chat_id: str, text: str = None, file_path: str = None, caption: str = None, file_type: str = "File", metadata: dict = None):
    try:
        if file_path:
            logger.info("Uploading %s to Rubika channel %s with metadata...", file_type, rubika_chat_id)
            rub_mid = await try_send_file_with_fallback(rubika_chat_id, file_path, caption, file_type, metadata=metadata)
        else:
            logger.info("Sending text to Rubika channel %s with metadata", rubika_chat_id)
            # ارسال مستقیم دیکشنری متادیتا
            res = await rb.send_message(chat_id=rubika_chat_id, text=text, metadata=metadata)
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

        # 1. استخراج مستقیم متادیتا از موجودیت‌های تلگرام
        meta = telethon_to_metadata(msg.entities)
        
        if msg.message and not msg.media:
            # Text-only: متن اصلی (بدون تغییر) + متادیتا ارسال می‌شود
            await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, text=msg.message, metadata=meta)
            return

        if msg.media:
            tmpdir = tempfile.mkdtemp()
            try:
                file_path = await msg.download_media(file=tmpdir)
                caption = msg.message or None
                ftype = guess_file_type_from_telethon(msg)
                if ftype == "Voice" and not os.path.splitext(file_path)[1]:
                    new_path = file_path + ".ogg"
                    os.rename(file_path, new_path)
                    file_path = new_path
                
                # ارسال فایل به همراه کپشن و متادیتا
                await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, file_path=file_path, caption=caption, file_type=ftype, metadata=meta)
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
        
        # تولید متادیتا برای پیام ادیت شده
        meta = telethon_to_metadata(msg.entities)
        new_text = msg.message or ""

        if new_text:
            logger.info("Editing Rubika message %s in chat %s", rubika_msg_id, rubika_chat_id)
            try:
                # استفاده از metadata در ادیت
                await rb.edit_message_text(chat_id=rubika_chat_id, message_id=rubika_msg_id, text=new_text, metadata=meta)
            except Exception as e:
                logger.exception("Failed to edit rubika message: %s", e)
        else:
            # اگر فقط مدیا کپشن دارد
            caption = msg.message or None
            if caption is not None:
                try:
                    await rb.edit_message_text(chat_id=rubika_chat_id, message_id=rubika_msg_id, text=caption, metadata=meta)
                except Exception as e:
                    logger.exception("Failed to edit rubika caption: %s", e)
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
    logger.info("Starting rubpy client...")
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
