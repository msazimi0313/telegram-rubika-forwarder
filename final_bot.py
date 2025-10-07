import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import types
from rubpy import BotClient
from rubpy.bot.models import Keypad

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    API_ID = int(os.environ.get("TELEGRAM_API_ID"))
    API_HASH = os.environ.get("TELEGRAM_API_HASH")
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
except (TypeError, ValueError) as e:
    print(f"خطا: یکی از متغیرهای محیطی تنظیم نشده یا فرمت آن اشتباه است: {e}")
    exit()

IRAN_TIMEZONE = pytz.timezone('Asia/Tehran')

# ===============================================================
# توابع کمکی
# ===============================================================
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
rubika_bot: BotClient | None = None
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

def create_rubika_keypad(telethon_buttons):
    if not telethon_buttons: return None
    keypad_rows = []
    for row in telethon_buttons:
        keypad_row = []
        for button in row:
            if isinstance(button, types.KeyboardButtonUrl):
                keypad_row.append({'text': button.text, 'url': button.url})
        if keypad_row: keypad_rows.append(keypad_row)
    return Keypad(rows=keypad_rows) if keypad_rows else None

# ===============================================================
# پردازشگر اصلی پیام‌ها
# ===============================================================
async def process_event(event, event_type):
    global stats, message_map
    if not rubika_bot: return

    if event_type == "new":
        message = event.message
        source_id = message.chat_id
        destination_id = routing_map.get(source_id)
        if not destination_id: return

        print(f"\n[پردازش پیام جدید] از {source_id} به {destination_id}")
        
        rubika_reply_to_id = None
        if message.is_reply and message.reply_to:
            telegram_reply_to_id = str(message.reply_to.reply_to_msg_id)
            mapping = message_map.get(telegram_reply_to_id)
            if mapping: rubika_reply_to_id = mapping.get("rubika_id")

        inline_keypad = create_rubika_keypad(message.buttons)

        try:
            caption = message.text or ""
            sent_rubika_message = None
            message_type = "unknown"
            file_path = None

            if message.media and isinstance(message.media, types.MessageMediaPoll):
                message_type = "poll"; poll = message.media.poll; question = poll.question
                options = [answer.text for answer in poll.answers]
                sent_rubika_message = await rubika_bot.send_poll(chat_id=destination_id, question=question, options=options)
            elif message.geo:
                message_type = "location"; geo = message.geo
                sent_rubika_message = await rubika_bot.send_location(chat_id=destination_id, latitude=geo.lat, longitude=geo.long, reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.contact:
                message_type = "contact"; contact = message.contact
                sent_rubika_message = await rubika_bot.send_contact(chat_id=destination_id, first_name=contact.first_name, last_name=contact.last_name or "", phone_number=contact.phone_number, reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.text and not message.media:
                message_type = "text"
                sent_rubika_message = await rubika_bot.send_message(destination_id, message.text, reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            # <---【اصلاح شد】: گیف‌ها به عنوان ویدیو ارسال می‌شوند تا خطا ندهند
            elif message.video and any(isinstance(attr, types.DocumentAttributeAnimated) for attr in message.video.attributes):
                 message_type = "video" # در آمار به عنوان ویدیو ثبت می‌شود
                 file_path = await user_client.download_media(message.video, file="downloads/")
                 sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='Video', reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.photo:
                message_type = "photo"; file_path = await user_client.download_media(message.photo, file="downloads/")
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='Image', reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.video:
                message_type = "video"; file_path = await user_client.download_media(message.video, file="downloads/")
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='Video', reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.audio:
                message_type = "audio"; file_path = await user_client.download_media(message.audio, file="downloads/")
                sent_rubika_message = await rubika_bot.send_music(chat_id=destination_id, file=file_path, text=caption, reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.voice:
                message_type = "voice"; file_path = await user_client.download_media(message.voice, file="downloads/")
                sent_rubika_message = await rubika_bot.send_voice(chat_id=destination_id, file=file_path, reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)
            elif message.document:
                message_type = "document"; file_path = await user_client.download_media(message.document, file="downloads/")
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='File', reply_to_message_id=rubika_reply_to_id, inline_keypad=inline_keypad)

            if file_path and os.path.exists(file_path): os.remove(file_path)
            if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
                telegram_id = str(message.id); rubika_id = sent_rubika_message.message_id
                message_map[telegram_id] = {"rubika_id": rubika_id, "destination_id": destination_id}
                save_data_to_file('message_map.json', message_map)
                stats["by_type"].setdefault(message_type, 0); stats["by_type"][message_type] += 1
                stats["total_forwarded"] = stats.get("total_forwarded", 0) + 1
                stats["last_activity_time"] = datetime.now(IRAN_TIMEZONE).isoformat()
                save_data_to_file('stats.json', stats)
                print(f"-> پیام از نوع '{message_type}' با موفقیت ارسال و مپ شد.")
        except Exception as e:
            error_message = f"!! خطا در پردازش پیام جدید: {e}"; print(error_message)
            stats["errors"] = stats.get("errors", 0) + 1; save_data_to_file('stats.json', stats)
            await send_admin_notification(f"❌ **خطا در ربات فورواردر** ❌\n\nهنگام پردازش پیام از کانال `{source_id}` خطای زیر رخ داد:\n`{e}`")
    
    elif event_type == "edited":
        edited_message = event.message; print(f"\n[پردازش ویرایش پیام] شناسه: {edited_message.id}")
        telegram_id = str(edited_message.id); mapping = message_map.get(telegram_id)
        if mapping:
            rubika_id = mapping["rubika_id"]; destination_id = mapping["destination_id"]
            new_content = edited_message.text or ""; new_keypad = create_rubika_keypad(edited_message.buttons)
            await rubika_bot.edit_message_text(destination_id, rubika_id, new_content)
            if new_keypad is not None: await rubika_bot.edit_message_keypad(destination_id, rubika_id, new_keypad)
            print(f"-> پیام ({rubika_id}) در روبیکا ({destination_id}) ویرایش شد.")
    
    elif event_type == "deleted":
        print(f"\n[پردازش حذف پیام] شناسه‌ها: {event.deleted_ids}")
        try:
            for deleted_id in event.deleted_ids:
                telegram_id = str(deleted_id)
                if telegram_id in message_map:
                    mapping = message_map[telegram_id]; rubika_id = mapping["rubika_id"]; destination_id = mapping["destination_id"]
                    await rubika_bot.delete_message(destination_id, rubika_id)
                    print(f"-> پیام متناظر ({rubika_id}) در روبیکا ({destination_id}) حذف شد.")
                    del message_map[telegram_id]
            save_data_to_file('message_map.json', message_map)
        except Exception as e: print(f"!! خطا در پردازش حذف پیام: {e}")

# <---【اصلاح شد】: مدیریت کامل پیام‌های خصوصی برای ادمین و غیرادمین
async def private_message_handler(event):
    global stats
    user_id = event.sender_id
    
    # اگر کاربر ادمین است، پنل مدیریت را نمایش بده
    if user_id in TELEGRAM_ADMIN_IDS:
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
            status_text = "✅ ربات فعال و در حال کار است.\n\n**— نقشه مسیردهی فعال —**\n"
            for tg_id, rb_id in routing_map.items(): status_text += f"`{tg_id}` ➡️ `{rb_id}`\n"
            await event.respond(status_text, parse_mode='markdown')
        elif command == "/clearstats" or "پاک کردن آمار" in command:
            stats = get_default_stats(); save_data_to_file('stats.json', stats)
            await event.respond("🗑 آمار ربات با موفقیت پاک و صفر شد.")
    
    # اگر کاربر ادمین نیست، پیام راهنما را ارسال کن
    else:
        user = await event.get_sender()
        await event.respond(f" سلام {user.first_name} عزیز! 🌸\n\nاین ربات جهت انتقال پیام بین کانال‌ها طراحی شده و قابلیت گفتگوی مستقیم را ندارد.")

# ===============================================================
# تابع اصلی برنامه (main)
# ===============================================================
async def main(event_queue):
    global user_client, bot_client, rubika_bot, routing_map, message_map, stats
    
    pairs = CHANNEL_MAP_STR.split(','); [routing_map.update({int(p.split(':', 1)[0].strip()): p.split(':', 1)[1].strip()}) for p in pairs if ':' in p]
    source_channel_ids = list(routing_map.keys())
    
    message_map = load_data_from_file('message_map.json', {}); stats = load_data_from_file('stats.json', get_default_stats())
    if not os.path.exists("downloads"): os.makedirs("downloads")

    print("در حال اتصال کلاینت‌ها...")
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    bot_client = TelegramClient('bot_session', API_ID, API_HASH)
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()

    @user_client.on(events.NewMessage(chats=source_channel_ids))
    async def handler(e): await event_queue.put(("new", e))
    @user_client.on(events.MessageEdited(chats=source_channel_ids))
    async def handler(e): await event_queue.put(("edited", e))
    @user_client.on(events.MessageDeleted(chats=source_channel_ids))
    async def handler(e): await event_queue.put(("deleted", e))
    # <---【اصلاح شد】: شنود تمام پیام‌های خصوصی
    @bot_client.on(events.NewMessage(private=True))
    async def handler(e): await private_message_handler(e)

    print("ربات آماده به کار است...")
    await user_client.start(); await bot_client.start(bot_token=TELEGRAM_BOT_TOKEN)
    print("کلاینت‌های تلگرام با موفقیت آنلاین شدند.")
    
    await send_admin_notification("✅ ربات فورواردر با موفقیت آنلاین شد و آماده دریافت پیام است.")
    
    await asyncio.gather(user_client.run_until_disconnected(), bot_client.run_until_disconnected())
