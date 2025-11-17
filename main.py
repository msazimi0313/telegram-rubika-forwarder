# main.py
import os
import asyncio
import logging
import tempfile
import sqlite3
import re
from typing import Optional, Tuple, Any, Dict, List   # NEW

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from rubpy.bot import BotClient
from rubpy.bot.exceptions import APIException
from rubpy.enums import ParseMode

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

MAP = {
    str(int(TG_CHANNEL_1)): RUBIKA_CHANNEL_1,
    str(int(TG_CHANNEL_2)): RUBIKA_CHANNEL_2,
}


tg_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
rb = BotClient(token=RUBIKA_BOT_AUTH)


# ----------------- DB -----------------
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


# ======================================================================
#    NEW: تابع تبدیل metadata روبیکا به متن با فرمت Markdown
# ======================================================================
def extract_formatted_text_from_metadata(text: str, metadata: Dict[str, Any]) -> Tuple[str, str]:
    """
    روبیکا فرمت را در metadata.entities می‌دهد.
    این تابع متن را با Markdown بازسازی می‌کند.
    خروجی: (text, ParseMode.MARKDOWN)
    """

    if not metadata or "entities" not in metadata:
        return text, None

    entities: List[Dict[str, Any]] = metadata.get("entities", [])
    if not entities:
        return text, None

    # معکوس مرتب می‌کنیم که offset ها خراب نشوند
    entities = sorted(entities, key=lambda e: e["offset"] + e["length"], reverse=True)

    t = text

    for e in entities:
        start = e["offset"]
        end = start + e["length"]
        tp = e["type"]

        if tp == "bold":
            t = t[:start] + "**" + t[start:end] + "**" + t[end:]

        elif tp == "italic":
            t = t[:start] + "_" + t[start:end] + "_" + t[end:]

        elif tp == "underline":
            t = t[:start] + "__" + t[start:end] + "__" + t[end:]

        elif tp == "strikethrough":
            t = t[:start] + "~~" + t[start:end] + "~~" + t[end:]

        elif tp == "code":
            t = t[:start] + "`" + t[start:end] + "`" + t[end:]

        elif tp == "spoiler":
            t = t[:start] + "||" + t[start:end] + "||" + t[end:]

    return t, ParseMode.MARKDOWN


# ======================================================================
#  باقی کدت تغییر نکرده، فقط در جاهای لازم از metadata استفاده شده
# ======================================================================

def _extract_message_id(result: Any) -> Optional[str]:
    if result is None:
        return None
    for attr in ("message_id", "id", "msg_id"):
        if hasattr(result, attr):
            return str(getattr(result, attr))
    if isinstance(result, dict):
        for key in ("message_id", "id", "msg_id"):
            if key in result:
                return str(result[key])
    return str(result)


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


# ----------------- NEW: هنگام ارسال پیام، metadata را اعمال می‌کنیم -----------------
async def forward_text_with_format(text, metadata, rubika_chat):
    formatted_text, mode = extract_formatted_text_from_metadata(text, metadata)
    return await rb.send_message(chat_id=rubika_chat, text=formatted_text, parse_mode=mode)


# ----------------- Forwarding Logic -----------------
async def forward_to_rubika_and_store(tg_chat_id: str, tg_message_id: int, rubika_chat_id: str, text: Optional[str] = None, file_path: Optional[str] = None, caption: Optional[str] = None, file_type: str = "File"):
    try:
        if file_path:
            cap_text, parse_mode = caption, None
            res = await rb.send_file(chat_id=rubika_chat_id, file=file_path, type=file_type, text=cap_text)
            rub_mid = _extract_message_id(res)

        else:
            # =================== THIS PART NEW ===================
            formatted, mode = extract_formatted_text_from_metadata(text, getattr(text, "metadata", {}))
            res = await rb.send_message(chat_id=rubika_chat_id, text=formatted, parse_mode=mode)
            # =====================================================

            rub_mid = _extract_message_id(res)

        if rub_mid:
            save_mapping(tg_chat_id, tg_message_id, rubika_chat_id, rub_mid)

        return rub_mid
    except Exception as e:
        logger.exception("forward error: %s", e)
        return None


# ----------------- Telethon Handlers -----------------
@tg_client.on(events.NewMessage(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def new_message_handler(event):
    try:
        msg = event.message
        tg_chat_id = str(event.chat_id)
        rubika_target = MAP.get(tg_chat_id)
        if not rubika_target:
            return

        # TEXT
        if msg.message and not msg.media:
            await forward_text_with_format(msg.message, msg.to_dict().get("entities", {}), rubika_target)
            return

        # MEDIA
        if msg.media:
            tmpdir = tempfile.mkdtemp()
            file_path = await msg.download_media(file=tmpdir)
            caption = msg.message or None
            ftype = guess_file_type_from_telethon(msg)
            await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, file_path=file_path, caption=caption, file_type=ftype)
            try:
                os.remove(file_path)
            except:
                pass

    except Exception as e:
        logger.exception("handler error: %s", e)


# ------------------- Edited -------------------
@tg_client.on(events.MessageEdited(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def edited_message_handler(event):
    try:
        msg = event.message
        tg_chat_id = str(event.chat_id)
        mapping = get_mapping(tg_chat_id, msg.id)
        if not mapping:
            return
        rubika_chat_id, rubika_msg_id = mapping

        new_text = msg.message or ""
        formatted, mode = extract_formatted_text_from_metadata(new_text, msg.to_dict().get("entities", {}))

        await rb.edit_message_text(chat_id=rubika_chat_id, message_id=rubika_msg_id, text=formatted, parse_mode=mode)

    except Exception as e:
        logger.exception("edit error: %s", e)


# ----------------- Deleted -----------------
@tg_client.on(events.MessageDeleted(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def deleted_message_handler(event):
    try:
        tg_chat_id = str(event.chat_id)
        for mid in event.deleted_ids:
            mapping = get_mapping(tg_chat_id, mid)
            if mapping:
                rubika_chat_id, rubika_msg_id = mapping
                await rb.delete_message(chat_id=rubika_chat_id, message_id=rubika_msg_id)
                delete_mapping(tg_chat_id, mid)
    except Exception as e:
        logger.exception("delete error: %s", e)


# ----------------- Startup -----------------
async def start_services():
    await rb.start()
    await tg_client.start()

    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    app.add_routes([web.get("/health", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await tg_client.run_until_disconnected()


def main():
    try:
        asyncio.run(start_services())
    except:
        pass
    finally:
        try:
            asyncio.run(rb.close())
        except:
            pass


if __name__ == "__main__":
    main()
