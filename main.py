# main.py
import os
import asyncio
import logging
import tempfile
import sqlite3
from typing import Optional, Tuple, Any

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from rubpy.bot import BotClient
from rubpy.bot.exceptions import APIException
# -------------------- NEW IMPORT --------------------
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
DB_PATH = os.environ.get("MAPPING_DB_PATH", "mappings.db")  # optional override

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
    """
    rubpy.send_message / send_file returns a MessageId-like value.
    Try common attribute/key names, otherwise fallback to str(result).
    """
    if result is None:
        return None
    # object attributes
    for attr in ("message_id", "id", "msg_id"):
        if hasattr(result, attr):
            return str(getattr(result, attr))
    # dict-like
    try:
        if isinstance(result, dict):
            for key in ("message_id", "id", "msg_id"):
                if key in result:
                    return str(result[key])
    except Exception:
        pass
    # fallback
    try:
        return str(result)
    except Exception:
        return None


def guess_file_type_from_telethon(msg) -> str:
    """Return one of rubpy accepted types: File, Image, Voice, Music, Gif, Video"""
    # Telethon message attributes (common ones)
    if getattr(msg, "photo", None):
        return "Image"
    if getattr(msg, "video", None):
        return "Video"
    # telegram voice notes are often msg.voice or msg.voice_note
    if getattr(msg, "voice", None) or getattr(msg, "voice_note", None):
        return "Voice"
    # animation/gif
    if getattr(msg, "gif", None) or getattr(msg, "animation", None):
        return "Gif"
    # fallback
    return "File"

# -------------------- NEW FUNCTION: Convert Telethon Message to Markdown --------------------
def convert_telethon_message_to_markdown(message) -> str:
    """
    Converts a Telethon message object (with entities) into Rubpy-compatible Markdown text.
    It returns the formatted text (string).
    
    Since Rubpy's BotAPI seems to support a Telegram-like Markdown V2,
    we use Telethon's built-in formatting functions for maximum compatibility.
    """
    # Telethon's built-in method to convert to markdown format (V2)
    # The result should be compatible with ParseMode.MARKDOWN in rubpy.
    # Note: Rubpy's Markdown has some differences (e.g., -- for underline), 
    # but using Telegram's default output is the most robust starting point.
    try:
        return message.to_markdown()
    except Exception as e:
        logger.warning("Failed to convert message to markdown: %s. Using raw text.", e)
        return message.message or ""
    

async def try_send_file_with_fallback(rubika_chat_id: str, local_path: str, caption: str, primary_type: str):
    """
    Try sending file with primary_type (e.g. Voice). If API returns INVALID_INPUT,
    try fallback to 'File' (generic).
    Returns the rubika message id (string) or None.
    
    NOTE: Added parse_mode=ParseMode.MARKDOWN to the send_file call.
    """
    try:
        res = await rb.send_file(
            chat_id=rubika_chat_id, 
            file=local_path, 
            type=primary_type, 
            text=caption,
            parse_mode=ParseMode.MARKDOWN  # <-- ADDED
        )
        return _extract_message_id(res)
    except APIException as e:
        # If server rejects the type (INVALID_INPUT), fallback to generic File
        msg = getattr(e, "message", str(e))
        logger.warning("send_file primary type %s failed: %s. Trying fallback to 'File'...", primary_type, msg)
        try:
            # pass file_name explicitly to help server detect type from extension
            file_name = os.path.basename(local_path)
            res2 = await rb.send_file(
                chat_id=rubika_chat_id, 
                file=local_path, 
                type="File", 
                text=caption, 
                file_name=file_name,
                parse_mode=ParseMode.MARKDOWN  # <-- ADDED
            )
            return _extract_message_id(res2)
        except Exception as e2:
            logger.exception("Fallback send_file(File) also failed: %s", e2)
            raise


async def forward_to_rubika_and_store(tg_chat_id: str, tg_message_id: int, rubika_chat_id: str, text: str = None, file_path: str = None, caption: str = None, file_type: str = "File"):
    """Send to rubika and store mapping (if successful)."""
    try:
        if file_path:
            logger.info("Uploading %s to Rubika channel %s ...", file_type, rubika_chat_id)
            rub_mid = await try_send_file_with_fallback(rubika_chat_id, file_path, caption, file_type)
        else:
            logger.info("Sending text to Rubika channel %s", rubika_chat_id)
            # Use parse_mode=ParseMode.MARKDOWN for text-only messages
            res = await rb.send_message(
                chat_id=rubika_chat_id, 
                text=text,
                parse_mode=ParseMode.MARKDOWN  # <-- ADDED
            )
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

        # -------------------- LOGIC CHANGE --------------------
        # The text/caption should be converted to Markdown regardless of media presence.
        markdown_text = convert_telethon_message_to_markdown(msg)

        if not msg.media and markdown_text:
            # Text-only
            await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, text=markdown_text)
            return

        if msg.media:
            # download media with extension if possible
            tmpdir = tempfile.mkdtemp()
            try:
                # prefer a filename that preserves extension
                file_path = await msg.download_media(file=tmpdir)
                # Use the converted markdown text as caption
                caption = markdown_text or None 
                ftype = guess_file_type_from_telethon(msg)
                # if we detected Voice but the file lacks extension, guess .ogg
                if ftype == "Voice" and not os.path.splitext(file_path)[1]:
                    new_path = file_path + ".ogg"
                    os.rename(file_path, new_path)
                    file_path = new_path
                await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, file_path=file_path, caption=caption, file_type=ftype)
            finally:
                # cleanup local file(s)
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
        msg = event.message  # edited message object
        tg_chat_id = str(event.chat_id)
        mapping = get_mapping(tg_chat_id, msg.id)
        if not mapping:
            logger.info("Edited message mapping not found for %s/%s — ignoring", tg_chat_id, msg.id)
            return
        rubika_chat_id, rubika_msg_id = mapping
        
        # -------------------- LOGIC CHANGE --------------------
        # Convert edited message (text/caption) to Markdown
        markdown_text = convert_telethon_message_to_markdown(msg)
        
        if markdown_text is not None:
            logger.info("Editing Rubika message %s in chat %s to: %s", rubika_msg_id, rubika_chat_id, markdown_text[:60])
            try:
                # Use parse_mode=ParseMode.MARKDOWN for editing text
                await rb.edit_message_text(
                    chat_id=rubika_chat_id, 
                    message_id=rubika_msg_id, 
                    text=markdown_text,
                    parse_mode=ParseMode.MARKDOWN  # <-- ADDED
                )
            except Exception as e:
                logger.exception("Failed to edit rubika message/caption: %s", e)
        # Note: If markdown_text is empty, it means the text was removed entirely, 
        # which is handled by the initial check or the successful edit (which clears the text if given empty string).
            
    except Exception as e:
        logger.exception("Error in edited_message_handler: %s", e)


@tg_client.on(events.MessageDeleted(chats=[int(TG_CHANNEL_1), int(TG_CHANNEL_2)]))
async def deleted_message_handler(event):
    try:
        deleted_ids = event.deleted_ids  # list of ints
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

    # health endpoint for UptimeRobot / Render
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
