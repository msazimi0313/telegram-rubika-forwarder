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


def get_python_indices(text: str, tg_offset: int, tg_length: int) -> Tuple[int, int]:
    """تبدیل آفست‌های UTF-16 تلگرام به ایندکس‌های پایتون"""
    if tg_offset == 0 and tg_length == 0:
        return 0, 0
        
    utf16_pos = 0
    py_start = -1
    py_end = -1
    
    if tg_offset == 0:
        py_start = 0
        
    for i, char in enumerate(text):
        if utf16_pos == tg_offset:
            py_start = i
        if utf16_pos == (tg_offset + tg_length):
            py_end = i
            break
        char_len = 2 if ord(char) > 0xFFFF else 1
        utf16_pos += char_len
        
    if py_start == -1 and utf16_pos == tg_offset:
        py_start = len(text)
    if py_end == -1: 
        py_end = len(text)
        
    return py_start, py_end


def get_entity_priority(entity):
    """
    اولویت‌بندی تگ‌ها برای اطمینان از ترتیب صحیح تودرتویی.
    اعداد کمتر به معنی 'بیرونی‌تر' بودن در نظر گرفته می‌شوند وقتی طول‌ها برابر است.
    """
    if isinstance(entity, MessageEntityBold): return 1
    if isinstance(entity, MessageEntityItalic): return 2
    if isinstance(entity, MessageEntityStrike): return 3
    if isinstance(entity, MessageEntityUnderline): return 4
    if isinstance(entity, MessageEntitySpoiler): return 5
    if isinstance(entity, MessageEntityCode): return 6
    if isinstance(entity, MessageEntityPre): return 7
    if isinstance(entity, MessageEntityTextUrl): return 8
    if isinstance(entity, MessageEntityBlockquote): return 9
    return 10


# --- تابع پیشرفته و اصلاح شده برای هندل کردن مارک‌داون‌های تودرتو ---
def apply_markdown_to_text(text: str, entities: list) -> str:
    if not entities or not text:
        return text
    
    # 1. محاسبه ایندکس‌های صحیح (رفع مشکل ایموجی و آفست)
    corrected_entities = []
    for ent in entities:
        start, end = get_python_indices(text, ent.offset, ent.length)
        length = end - start
        corrected_entities.append({'start': start, 'end': end, 'length': length, 'ent': ent})

    # 2. شناسایی محدوده‌های "بلاک کد"
    code_ranges = []
    for item in corrected_entities:
        if isinstance(item['ent'], MessageEntityPre):
            code_ranges.append((item['start'], item['end']))
            
    def is_inside_code_block(pos):
        for start, end in code_ranges:
            if start <= pos < end: 
                return True
        return False

    insertions = []
    
    for item in corrected_entities:
        ent = item['ent']
        start = item['start']
        end = item['end']
        length = item['length']
        
        if not isinstance(ent, MessageEntityPre) and is_inside_code_block(start):
            continue

        tag_start = ""
        tag_end = ""
        
        if isinstance(ent, MessageEntityBold):
            tag_start, tag_end = "**", "**"
        elif isinstance(ent, MessageEntityItalic):
            tag_start, tag_end = "__", "__"
        elif isinstance(ent, MessageEntityStrike):
            tag_start, tag_end = "~~", "~~"
        elif isinstance(ent, MessageEntityUnderline):
            tag_start, tag_end = "--", "--"
        elif isinstance(ent, MessageEntitySpoiler):
            tag_start, tag_end = "||", "||"
        elif isinstance(ent, MessageEntityCode):
            tag_start, tag_end = "`", "`"
        elif isinstance(ent, MessageEntityPre):
            tag_start, tag_end = "```", "```"
        elif isinstance(ent, MessageEntityTextUrl):
            tag_start = "["
            tag_end = f"]({ent.url})"
        elif isinstance(ent, MessageEntityBlockquote):
            tag_start = "> "
            tag_end = "" 

        if tag_start:
            priority = get_entity_priority(ent)
            
            # --- منطق سورتینگ جدید برای حل مشکل ترتیب تگ‌ها ---
            # ساختار کلید سورت: (Index, Is_Start, Length_Factor, Priority_Factor, Tag_String)
            # هدف: اولویت‌بندی به شکلی که تگ‌های بیرونی زودتر باز شوند و دیرتر بسته شوند.
            
            # برای شروع تگ (Is_Start=1):
            # - اولویت (Priority): برای باز شدن، تگ با اولویت عدد کمتر (مثلا بولد=1) باید زودتر پردازش شود (بیرونی باشد)
            #   اما چون لیست را Descending (نزولی) سورت می‌کنیم، آیتم‌های 'بزرگتر' در لیست اول می‌آیند و اول پردازش می‌شوند.
            #   برای اینکه تگ بیرونی (مثلا A) بعد از تگ درونی (مثلا B) در لیست قرار بگیرد (تا اول B پردازش شود و متن بشود B... سپس A پردازش شود و متن بشود AB...)
            #   باید A 'کوچکتر' از B باشد.
            #   پس Priority کمتر (1) باید باعث کوچکتر شدن شود. (1 < 2). این درست است.
            # - طول (Length): تگ بلندتر باید بیرونی باشد. پس باید کوچکتر باشد. (-length).
            
            insertions.append((start, 1, -length, priority, tag_start))
            
            if tag_end:
                # برای پایان تگ (Is_Start=0):
                # - تگ بیرونی (A) باید دیرتر از تگ درونی (B) بسته شود. -> ... </B></A>
                #   یعنی در لیست پردازش، اول باید A باشد (درج </A>) و بعد B (درج </B>).
                #   یعنی A باید 'بزرگتر' از B باشد (در سورت نزولی).
                #   A (Priority 1) باید بزرگتر از B (Priority 2) شود؟
                #   پس باید از منفی اولویت استفاده کنیم: -1 > -2.
                
                insertions.append((end, 0, length, -priority, tag_end))
    
    # مرتب‌سازی نزولی
    insertions.sort(reverse=True)
    
    res_text = text
    for item in insertions:
        index = item[0]
        string_to_insert = item[4] # ایندکس 4 رشته تگ است
        
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

        pending_key = (tg_chat_id, msg.id)
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
            upload_event.set()
            PENDING_UPLOADS.pop(pending_key, None)
            
    except Exception as e:
        logger.exception("Error in new_message_handler: %s", e)


@tg_client.on(events.MessageEdited(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def edited_message_handler(event):
    try:
        msg = event.message
        tg_chat_id = str(event.chat_id)
        
        mapping = get_mapping(tg_chat_id, msg.id)
        if not mapping:
            pending_key = (tg_chat_id, msg.id)
            if pending_key in PENDING_UPLOADS:
                logger.info("Edit received for pending upload %s/%s. Waiting...", tg_chat_id, msg.id)
                await PENDING_UPLOADS[pending_key].wait()
                mapping = get_mapping(tg_chat_id, msg.id)
        
        if not mapping:
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
