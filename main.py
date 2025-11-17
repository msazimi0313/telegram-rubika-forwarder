# main.py
import os
import asyncio
import logging
import tempfile
import sqlite3
import re
import html
from typing import Optional, Tuple, Any, List, Dict

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from rubpy.bot import BotClient
from rubpy.bot.exceptions import APIException
from rubpy.enums import ParseMode  # <- اضافه شد

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
    if getattr(msg, "photo", None):
        return "Image"
    if getattr(msg, "video", None):
        return "Video"
    if getattr(msg, "voice", None) or getattr(msg, "voice_note", None):
        return "Voice"
    if getattr(msg, "gif", None) or getattr(msg, "animation", None):
        return "Gif"
    return "File"


def _map_entity_to_html_tags(ent_type: str, ent: Dict) -> Tuple[str, str]:
    """
    Map an entity type (from metadata) to opening and closing HTML tags.
    ent is kept for types that need extra data (e.g. url).
    """
    t = ent_type.lower()
    if t in ("bold", "strong", "b"):
        return "<b>", "</b>"
    if t in ("italic", "em", "i"):
        return "<i>", "</i>"
    if t in ("underline", "u"):
        return "<u>", "</u>"
    if t in ("strikethrough", "strike", "s", "del", "deleted"):
        return "<s>", "</s>"
    if t in ("code",):
        return "<code>", "</code>"
    if t in ("pre", "preformatted"):
        return "<pre>", "</pre>"
    if t in ("text_link", "link", "url"):
        url = ent.get("url") or ent.get("href") or ent.get("link")
        if url:
            return f'<a href="{html.escape(url, quote=True)}">', "</a>"
        else:
            return "<a>", "</a>"
    if t in ("spoiler",):
        # rubika/html may not support telegram-specific spoiler tag;
        # use a generic span with attribute class (best-effort).
        return '<span data-spoiler="true">', "</span>"
    # fallback: no-op tags
    return "", ""


def build_text_from_entities_html(text: str, entities: List[Dict]) -> str:
    """
    Best-effort: wrap ranges in HTML tags according to entities list.
    entities: list of dicts with at least 'offset','length','type'
    NOTE: offsets often specified in UTF-16 code units (platform dependent).
    We do a best-effort using Python string indices (may diverge for some unicode).
    """
    if not entities:
        return text

    inserts_open = {}  # idx -> list of open tags
    inserts_close = {}  # idx -> list of close tags

    for ent in entities:
        try:
            offset = int(ent.get("offset", ent.get("start", 0)))
            length = int(ent.get("length", ent.get("end", 0)) or 0)
        except Exception:
            continue
        etype = ent.get("type") or ent.get("entity") or ent.get("tag") or ""
        start = max(0, offset)
        end = max(0, start + length)
        open_tag, close_tag = _map_entity_to_html_tags(etype, ent)
        if open_tag:
            inserts_open.setdefault(start, []).append(open_tag)
        if close_tag:
            inserts_close.setdefault(end, []).append(close_tag)

    # build final string
    out_parts = []
    L = len(text)
    for i in range(0, L + 1):
        # open tags at position i
        if i in inserts_open:
            out_parts.append("".join(inserts_open[i]))
        if i < L:
            out_parts.append(html.escape(text[i]))
        # close tags *after* char at position i-1 (i == end)
        if i in inserts_close:
            # close in reverse order of opens (stack-like)
            out_parts.append("".join(reversed(inserts_close[i])))

    return "".join(out_parts)


def build_text_from_metadata(text: Optional[str], metadata: Any) -> Optional[Tuple[str, Optional[str]]]:
    """
    If metadata is present and contains parse hints/entities, build transformed text and parse_mode.
    Returns (transformed_text, parse_mode) or (original_text, None) if nothing applied.
    """
    if not text:
        return text, None
    if not metadata:
        return text, None

    # If metadata explicitly contains parse_mode, trust it
    meta = metadata if isinstance(metadata, dict) else getattr(metadata, "__dict__", None) or metadata

    # attempt to get parse_mode
    parse_mode = None
    if isinstance(meta, dict):
        pm = meta.get("parse_mode") or meta.get("parseMode") or meta.get("format")
        if isinstance(pm, str):
            if pm.strip().upper() in ("HTML", "MARKUP", "HTML_MODE"):
                return text, ParseMode.HTML
            if pm.strip().upper() in ("MARKDOWN", "MARKDOWN_V2", "MD", "MD2"):
                return text, ParseMode.MARKDOWN

    # if entities present, try to reconstruct HTML
    entities = None
    if isinstance(meta, dict):
        entities = meta.get("entities") or meta.get("message_entities") or meta.get("marks") or meta.get("markups")
    # if metadata is object-like, try attribute
    if entities is None:
        entities = getattr(meta, "entities", None)

    if entities:
        try:
            # normalize entities: if they're objects convert to dict-like
            ents = []
            for e in entities:
                if isinstance(e, dict):
                    ents.append(e)
                else:
                    # try read attributes
                    d = {}
                    for k in ("offset", "length", "type", "url", "start", "end", "entity"):
                        if hasattr(e, k):
                            d[k] = getattr(e, k)
                    # some libraries use 'entity' or 'tag'
                    ents.append(d)
            transformed = build_text_from_entities_html(text, ents)
            logger.info("Built text from metadata entities (using HTML).")
            return transformed, ParseMode.HTML
        except Exception as ex:
            logger.exception("Failed to build text from metadata entities: %s", ex)
            # fall through to normal detection

    # nothing usable in metadata
    return text, None


def prepare_text_and_mode(text: Optional[str], metadata: Any = None) -> (Optional[str], Optional[str]):
    """
    Inspect `text` and optional `metadata` for common markers and return:
      (possibly_transformed_text, parse_mode)
    Priority:
      1) metadata-driven parse_mode/entities (if provided)
      2) HTML tag presence
      3) custom --underline-- -> HTML
      4) common markdown markers -> MARKDOWN
      5) fallback: None
    """
    # 1) metadata first (if any)
    if metadata:
        built_text, pm = build_text_from_metadata(text, metadata)
        if pm:
            logger.info("Using parse_mode from metadata: %s", pm)
            return built_text, pm
        # if metadata returned None for parse_mode, continue to heuristic detection

    if not text:
        return text, None

    t = text

    # 2) quick HTML tag detection -> use HTML mode
    if re.search(r"</?[a-zA-Z][^>]*>", t):
        return t, ParseMode.HTML

    # 3) convert custom underline markers: --text-- -> <u>text</u>
    def _underline_repl(m):
        inner = m.group(1)
        return f"<u>{html.escape(inner)}</u>"

    if re.search(r"--([^-\n][\s\S]*?)--", t):
        t = re.sub(r"--([^-\n][\s\S]*?)--", _underline_repl, t)
        return t, ParseMode.HTML

    # 4) markdown heuristics
    markdown_patterns = [
        r"\*\*",    # **bold**
        r"__[^_\n].*?__",  # __italic__ (user sample)
        r"(?<!`)\*[^*\n].*?\*(?!`)",  # *italic*
        r"(?<!`)_([^_\n].*?)_(?!`)",  # _italic_
        r"`{1,3}[^`]+`{1,3}",  # `code` or ```code```
        r"~~[^~\n].*?~~",  # ~~strikethrough~~
        r"\|\|[^|\n].*?\|\|",  # ||spoiler||
        r"^\s*>",  # blockquote lines
    ]
    combined = "|".join(f"({p})" for p in markdown_patterns)
    if re.search(combined, t, flags=re.MULTILINE):
        return t, ParseMode.MARKDOWN

    return t, None


async def try_send_file_with_fallback(rubika_chat_id: str, local_path: str, caption: Optional[str], primary_type: str, metadata: Any = None):
    """
    Try sending file with primary_type (e.g. Voice). If API returns INVALID_INPUT,
    try fallback to 'File' (generic).
    Now also passes parse_mode detected from caption or metadata.
    Returns the rubika message id (string) or None.
    """
    try:
        cap_text, parse_mode = prepare_text_and_mode(caption, metadata=metadata)
        kwargs = {}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        res = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type=primary_type, text=cap_text, **kwargs)
        return _extract_message_id(res)
    except APIException as e:
        msg = getattr(e, "message", str(e))
        logger.warning("send_file primary type %s failed: %s. Trying fallback to 'File'...", primary_type, msg)
        try:
            file_name = os.path.basename(local_path)
            cap_text, parse_mode = prepare_text_and_mode(caption, metadata=metadata)
            kwargs = {"file_name": file_name}
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            res2 = await rb.send_file(chat_id=rubika_chat_id, file=local_path, type="File", text=cap_text, **kwargs)
            return _extract_message_id(res2)
        except Exception as e2:
            logger.exception("Fallback send_file(File) also failed: %s", e2)
            raise


async def forward_to_rubika_and_store(tg_chat_id: str, tg_message_id: int, rubika_chat_id: str, text: Optional[str] = None, file_path: Optional[str] = None, caption: Optional[str] = None, file_type: str = "File", metadata: Any = None):
    """Send to rubika and store mapping (if successful)."""
    try:
        if file_path:
            logger.info("Uploading %s to Rubika channel %s ...", file_type, rubika_chat_id)
            rub_mid = await try_send_file_with_fallback(rubika_chat_id, file_path, caption, file_type, metadata=metadata)
        else:
            logger.info("Sending text to Rubika channel %s", rubika_chat_id)
            send_text, parse_mode = prepare_text_and_mode(text, metadata=metadata)
            kwargs = {}
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            res = await rb.send_message(chat_id=rubika_chat_id, text=send_text, **kwargs)
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

        # try to obtain metadata if present (best-effort)
        metadata = None
        try:
            metadata = getattr(msg, "metadata", None) or getattr(event, "metadata", None) or getattr(event, "raw_update", None)
        except Exception:
            metadata = None

        if msg.message and not msg.media:
            # Text-only
            text = msg.message
            await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, text=text, metadata=metadata)
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
                await forward_to_rubika_and_store(tg_chat_id, msg.id, rubika_target, file_path=file_path, caption=caption, file_type=ftype, metadata=metadata)
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
        msg = event.message  # edited message object
        tg_chat_id = str(event.chat_id)
        mapping = get_mapping(tg_chat_id, msg.id)
        if not mapping:
            logger.info("Edited message mapping not found for %s/%s — ignoring", tg_chat_id, msg.id)
            return
        rubika_chat_id, rubika_msg_id = mapping

        # try to obtain metadata if present (best-effort)
        metadata = None
        try:
            metadata = getattr(msg, "metadata", None) or getattr(event, "metadata", None) or getattr(event, "raw_update", None)
        except Exception:
            metadata = None

        new_text = msg.message or ""
        if new_text:
            logger.info("Editing Rubika message %s in chat %s to: %s", rubika_msg_id, rubika_chat_id, new_text[:60])
            try:
                edited_text, parse_mode = prepare_text_and_mode(new_text, metadata=metadata)
                kwargs = {}
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode
                await rb.edit_message_text(chat_id=rubika_chat_id, message_id=rubika_msg_id, text=edited_text, **kwargs)
            except Exception as e:
                logger.exception("Failed to edit rubika message: %s", e)
        else:
            caption = msg.message or None
            if caption is not None:
                try:
                    cap_text, parse_mode = prepare_text_and_mode(caption, metadata=metadata)
                    kwargs = {}
                    if parse_mode:
                        kwargs["parse_mode"] = parse_mode
                    await rb.edit_message_text(chat_id=rubika_chat_id, message_id=rubika_msg_id, text=cap_text, **kwargs)
                except Exception as e:
                    logger.exception("Failed to edit rubika caption: %s", e)
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
