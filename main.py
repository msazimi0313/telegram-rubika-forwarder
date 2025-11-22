# main.py
import os
import asyncio
import logging
import tempfile
import sqlite3
import importlib.metadata
from typing import Optional, Tuple, Any, Dict

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityStrike, 
    MessageEntityUnderline, MessageEntitySpoiler, MessageEntityCode, 
    MessageEntityPre, MessageEntityTextUrl, MessageEntityBlockquote
)

from rubpy import BotClient
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

# ----------------- Global State -----------------
MAP = {
    str(int(TG_CHANNEL_1)): RUBIKA_CHANNEL_1,
    str(int(TG_CHANNEL_2)): RUBIKA_CHANNEL_2,
}

# دیکشنری برای نگهداری پیام‌های در حال آپلود
# Key: (tg_chat_id, tg_message_id), Value: asyncio.Event
PENDING_UPLOADS: Dict[Tuple[str, int], asyncio.Event] = {}

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


def apply_markdown_to_text(text: str, entities: list) -> str:
    if not entities or not text:
        return text
    
    code_ranges = []
    for ent in entities:
        if isinstance(ent, MessageEntityPre):
            code_ranges.append((ent.offset, ent.offset + ent.length))
            
    def is_inside_code_block(pos):
        for start, end in code_ranges:
            if start <= pos < end: 
                return True
        return False

    insertions = []
    entities.sort(key=lambda ent: ent.offset)

    for ent in entities:
        start = ent.offset
        end = ent.offset + ent.length
        
        if not isinstance(ent, MessageEntityPre) and is_inside_code_block(start):
            continue

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
            insertions.append((start, "--"))
            insertions.append((end, "--"))
        elif isinstance(ent, MessageEntitySpoiler):
            insertions.append((start, "||"))
            insertions.append((end, "||"))
        elif isinstance(ent, MessageEntityCode):
            insertions.append((start, "`"))
            insertions.append((end, "`"))
        elif isinstance(ent, MessageEntityPre):
            insertions.append((start, "```"))
            insertions.append((end, "```")) 
        elif isinstance(ent, MessageEntityTextUrl):
            insertions.append((start, "["))
            insertions.append((end, f"]({ent.url})"))
        elif isinstance(ent, MessageEntityBlockquote):
             insertions.append((start, "> "))
    
    insertions.sort(key=lambda x: x[0], reverse=True)
    
    res_text = text
    for index, string_to_insert in insertions:
        if 0 <= index <= len(res_text):
            res_text = res_text[:index] + string_to_insert + res_text[index:]
            
    return res_text


async def try_send_file_with_fallback(rubika_chat_id: str, local_path: str, caption: str, primary_type: str):
    try:
        res = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type=primary_type, text=caption, parse_mode=ParseMode.MARKDOWN)
        return _extract_message_id(res)
    except APIException as e:
        msg = getattr(e, "message", str(e))
        logger.warning("send_file primary type %s failed: %s. Trying fallback...", primary_type, msg)
        try:
            file_name = os.path.basename(local_path)
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
            return

        # ایجاد کلید منحصر به فرد برای پیام
        pending_key = (tg_chat_id, msg.id)
        # ایجاد رویداد انتظار
        upload_event = asyncio.Event()
        PENDING_UPLOADS[pending_key] = upload_event

        try:
            if msg.message:
                markdown_text = apply_markdown_to_text(msg.message, msg.entities)
            else:
                markdown_text = ""
            
            if (msg.message or msg.entities) and not msg.media:
                await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, text=markdown_text)
                return

            if msg.media:
                tmpdir = tempfile.mkdtemp()
                try:
                    file_path = await msg.download_media(file=tmpdir)
                    caption = markdown_text or None
                    
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
        finally:
            # در نهایت، چه آپلود موفق باشد چه خطا، رویداد را آزاد می‌کنیم
            # تا اگر ادیت منتظر است، از حالت انتظار خارج شود
            upload_event.set()
            PENDING_UPLOADS.pop(pending_key, None)
            
    except Exception as e:
        logger.exception("Error in new_message_handler: %s", e)


@tg_client.on(events.MessageEdited(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def edited_message_handler(event):
    try:
        msg = event.message
        tg_chat_id = str(event.chat_id)
        
        # 1. ابتدا چک می‌کنیم آیا پیام در دیتابیس هست؟
        mapping = get_mapping(tg_chat_id, msg.id)
        
        # 2. اگر نبود، چک می‌کنیم آیا در حال آپلود است؟
        if not mapping:
            pending_key = (tg_chat_id, msg.id)
            if pending_key in PENDING_UPLOADS:
                logger.info("Edit received for pending upload %s/%s. Waiting for upload to finish...", tg_chat_id, msg.id)
                # منتظر می‌مانیم تا آپلود تمام شود
                await PENDING_UPLOADS[pending_key].wait()
                # دوباره چک می‌کنیم
                mapping = get_mapping(tg_chat_id, msg.id)
        
        if not mapping:
            # اگر بعد از انتظار هم پیدا نشد (یعنی آپلود فیل شده)، بیخیال می‌شویم
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
                # شاید در حال آپلود بوده و قبل از ذخیره شدن پاک شده
                # اینجا هم می‌توان منتظر ماند اما معمولا حذف اولویت کمتری نسبت به ادیت دارد
                continue
            rubika_chat_id, rubika_msg_id = mapping
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
        logger.info("Starting rubpy client...")
        
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
    logger.info("Health endpoint started on port %s", PORT)
    
    logger.info("Running until disconnected...")
    await tg_client.run_until_disconnected()


def main():
    try:
        asyncio.run(start_services())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            asyncio.run(rb.close())
        except Exception:
            pass

if __name__ == "__main__":
    main()
