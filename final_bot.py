import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
import mimetypes
from aiohttp import ClientSession
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import types
from rubpy import Client

# ===============================================================
# بخش تنظیمات (بدون تغییر)
# ===============================================================
try:
    API_ID = int(os.environ.get("TELEGRAM_API_ID"))
    API_HASH = os.environ.get("TELEGRAM_API_HASH")
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_AUTH_KEY = os.environ.get("RUBIKA_AUTH_KEY")
    RUBIKA_PRIVATE_KEY = os.environ.get("RUBIKA_PRIVATE_KEY")
except (TypeError, ValueError) as e:
    print(f"خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است: {e}")
    exit()

IRAN_TIMEZONE = pytz.timezone('Asia/Tehran')
# ... (توابع کمکی و admin_command_handler بدون تغییر) ...
def get_default_stats():
    return {"total_forwarded": 0, "by_type": {}, "errors": 0, "last_activity_time": None}
def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data
def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

user_client: TelegramClient | None = None
bot_client: TelegramClient | None = None
rubika_self: Client | None = None
routing_map = {}
message_map = {}
stats = {}

async def send_admin_notification(text):
    if bot_client:
        for admin_id in TELEGRAM_ADMIN_IDS:
            try:
                await bot_client.send_message(admin_id, text, parse_mode='md')
            except Exception as e:
                print(f"Failed to send notification to admin {admin_id}: {e}")

def format_caption_with_buttons(caption, telethon_buttons):
    if not telethon_buttons:
        return caption
    links_text = "\n\n🔗 لینک‌ها:\n"
    has_links = False
    for row in telethon_buttons:
        for button in row:
            if isinstance(button, types.KeyboardButtonUrl):
                links_text += f"▪️ {button.text}: {button.url}\n"
                has_links = True
    return caption + links_text if has_links else caption


# ===============================================================
# پردازشگر اصلی پیام‌ها (نسخه نهایی)
# ===============================================================
async def process_event(event, event_type):
    global stats, message_map
    if not rubika_self: return

    if event_type == "new":
        message = event.message
        source_id = message.chat_id
        destination_guid = routing_map.get(source_id)
        if not destination_guid: return

        print(f"\n[پردازش پیام جدید] از {source_id} به {destination_guid}")
        rubika_reply_to_id = None
        if message.is_reply and message.reply_to:
            telegram_reply_to_id = str(message.reply_to.reply_to_msg_id)
            mapping = message_map.get(telegram_reply_to_id)
            if mapping: rubika_reply_to_id = mapping.get("rubika_id")

        try:
            base_caption = message.text or ""
            caption_with_links = format_caption_with_buttons(base_caption, message.buttons)
            sent_rubika_message = None
            message_type = "unknown"
            file_path = None

            if not caption_with_links.strip() and not message.media:
                print("-> پیام خالی نادیده گرفته شد.")
                return

            if message.media and not isinstance(message.media, (types.MessageMediaPoll, types.MessageMediaGeo, types.MessageMediaContact)):
                print("-> پیام حاوی رسانه است. شروع دانلود...")
                file_path = await user_client.download_media(message, file="downloads/")
                print(f"-> دانلود کامل شد: {file_path}")

                file_size = os.path.getsize(file_path)
                file_name = os.path.basename(file_path)
                mime_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
                message_type = "photo" if message.photo else "video" if message.video else "audio" if message.audio or message.voice else "document"

                print("-> مرحله ۱: درخواست لینک آپلود از روبیکا...")
                upload_data = await rubika_self.request_send_file(file_name=file_name, size=file_size, mime=mime_type)
                
                print("-> مرحله ۲: شروع آپلود دستی...")
                with open(file_path, 'rb') as f:
                    file_bytes = f.read()

                async with ClientSession() as session:
                    headers = {
                        'auth': rubika_self.auth,
                        'file-id': str(upload_data['id']),
                        'access-hash-send': upload_data['access_hash_send']
                    }
                    # 【اصلاح نهایی و قطعی】: استفاده از متد POST به جای PUT
                    async with session.post(upload_data['upload_url'], data=file_bytes, headers=headers) as response:
                        if response.status == 200:
                            print("-> آپلود دستی موفق بود.")
                        else:
                            raise Exception(f"خطا در آپلود دستی: {response.status} {await response.text()}")

                print("-> مرحله ۳: ارسال پیام نهایی...")
                sent_rubika_message = await rubika_self.send_message(
                    object_guid=destination_guid,
                    message=caption_with_links,
                    file_inline=upload_data,
                    reply_to_message_id=rubika_reply_to_id
                )

            elif message.text and not message.media:
                message_type = "text"
                sent_rubika_message = await rubika_self.send_message(
                    object_guid=destination_guid,
                    text=caption_with_links,
                    reply_to_message_id=rubika_reply_to_id
                )
            
            # ... (بقیه کد بدون تغییر)
            elif message.media:
                pass 

            if file_path and os.path.exists(file_path): os.remove(file_path)

            if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
                telegram_id = str(message.id)
                rubika_id = sent_rubika_message.message_id
                message_map[telegram_id] = {"rubika_id": rubika_id, "destination_id": destination_guid}
                save_data_to_file('message_map.json', message_map)
                stats["by_type"].setdefault(message_type, 0); stats["by_type"][message_type] += 1
                stats["total_forwarded"] = stats.get("total_forwarded", 0) + 1
                stats["last_activity_time"] = datetime.now(IRAN_TIMEZONE).isoformat()
                save_data_to_file('stats.json', stats)
                print(f"-> پیام از نوع '{message_type}' با موفقیت ارسال و مپ شد.")

        except Exception as e:
            error_message = f"!! خطا در پردازش پیام جدید: {e}"
            print(error_message)
            stats["errors"] = stats.get("errors", 0) + 1
            save_data_to_file('stats.json', stats)
            await send_admin_notification(f"❌ **خطا در ربات فورواردر** ❌\n\nهنگام پردازش پیام از کانال `{source_id}` خطای زیر رخ داد:\n`{e}`")

    elif event_type == "edited":
        # ... (کد ویرایش بدون تغییر)
        edited_message = event.message
        telegram_id = str(edited_message.id)
        mapping = message_map.get(telegram_id)
        if mapping:
            new_content = edited_message.text or ""
            new_content_with_links = format_caption_with_buttons(new_content, edited_message.buttons)
            await rubika_self.edit_message(mapping["destination_id"], mapping["rubika_id"], new_content_with_links)
            print(f"-> پیام ({mapping['rubika_id']}) ویرایش شد.")

    elif event_type == "deleted":
        # ... (کد حذف بدون تغییر)
        try:
            messages_to_delete = {}
            for deleted_id in event.deleted_ids:
                telegram_id = str(deleted_id)
                if telegram_id in message_map:
                    mapping = message_map.pop(telegram_id)
                    guid = mapping["destination_id"]
                    if guid not in messages_to_delete: messages_to_delete[guid] = []
                    messages_to_delete[guid].append(mapping["rubika_id"])
            for guid, msg_ids in messages_to_delete.items():
                await rubika_self.delete_messages(guid, msg_ids)
                print(f"-> {len(msg_ids)} پیام در {guid} حذف شد.")
            save_data_to_file('message_map.json', message_map)
        except Exception as e: print(f"!! خطا در پردازش حذف پیام: {e}")

# ... (بقیه فایل، شامل admin_command_handler و main، بدون تغییر است) ...
async def admin_command_handler(event):
    global stats
    command = event.raw_text.lower()
    if command == "/start" or command == "/admin":
        await event.respond("پنل مدیریت:", buttons=[["📊 آمار (/stats)"], ["⚙️ وضعیت ربات (/status)"], ["🗑 پاک کردن آمار (/clearstats)"]])
    elif command == "/stats" or "آمار" in command:
        last_time_str = "هنوز فعالیتی ثبت نشده"
        if stats.get("last_activity_time"):
            last_time_iso = datetime.fromisoformat(stats['last_activity_time'])
            jalali_time = jdatetime.datetime.fromgregorian(datetime=last_time_iso)
            last_time_str = jalali_time.strftime('%Y/%m/%d - %H:%M:%S')
        stats_text = (f"📊 **آمار عملکرد ربات**\n\n🔹 **کل پیام‌های فوروارد شده:** {stats.get('total_forwarded', 0)}\n🔸 **آخرین فعالیت:** {last_time_str}\n🔺 **تعداد خطاها:** {stats.get('errors', 0)}\n\n📦 **تفکیک نوع پیام:**\n")
        for msg_type, count in stats.get("by_type", {}).items(): stats_text += f"  - `{msg_type}`: {count}\n"
        await event.respond(stats_text, parse_mode='markdown')
    elif command == "/status" or "وضعیت" in command:
        status_text = "✅ ربات فعال و در حال کار است. (حالت سلف‌بات)\n\n**— نقشه مسیردهی فعال —**\n"
        for tg_id, rb_id in routing_map.items(): status_text += f"`{tg_id}` ➡️ `{rb_id}`\n"
        await event.respond(status_text, parse_mode='markdown')
    elif command == "/clearstats" or "پاک کردن آمار" in command:
        stats = get_default_stats()
        save_data_to_file('stats.json', stats)
        await event.respond("🗑 آمار ربات با موفقیت پاک و صفر شد.")

async def main(event_queue):
    global user_client, bot_client, rubika_self, routing_map, message_map, stats
    pairs = CHANNEL_MAP_STR.split(','); [routing_map.update({int(p.split(':', 1)[0].strip()): p.split(':', 1)[1].strip()}) for p in pairs if ':' in p]
    source_channel_ids = list(routing_map.keys())
    message_map = load_data_from_file('message_map.json', {}); stats = load_data_from_file('stats.json', get_default_stats())
    if not os.path.exists("downloads"): os.makedirs("downloads")
    print("در حال اتصال کلاینت‌ها...")
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    bot_client = TelegramClient('bot_session', API_ID, API_HASH)
    rubika_self = Client("rubika_account", auth=RUBIKA_AUTH_KEY, private_key=RUBIKA_PRIVATE_KEY)
    await rubika_self.start()
    @user_client.on(events.NewMessage(chats=source_channel_ids))
    async def handler(e): await event_queue.put(("new", e))
    @user_client.on(events.MessageEdited(chats=source_channel_ids))
    async def handler(e): await event_queue.put(("edited", e))
    @user_client.on(events.MessageDeleted(chats=source_channel_ids))
    async def handler(e): await event_queue.put(("deleted", e))
    @bot_client.on(events.NewMessage(from_users=TELEGRAM_ADMIN_IDS))
    async def handler(e): await admin_command_handler(e)
    print("ربات آماده به کار است...")
    await user_client.start(); await bot_client.start(bot_token=TELEGRAM_BOT_TOKEN)
    print("کلاینت‌های تلگرام و روبیکا (سلف) با موفقیت آنلاین شدند.")
    await send_admin_notification("✅ ربات فورواردر با موفقیت آنلاین شد. (حالت: سلف‌بات)")
    await asyncio.gather(user_client.run_until_disconnected(), bot_client.run_until_disconnected())
