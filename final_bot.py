import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import types as telethon_types # تغییر نام برای جلوگیری از تداخل
from rubpy import Client
# <---【اصلاح نهایی و قطعی】: وارد کردن کلاس‌ها از ماژول types
from rubpy.types import InputPhoto, InputVideo, InputMusic, InputVoice, InputFile

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
except (TypeError, ValueError) as e:
    print(f"خطا: یکی از متغیرهای محیطی تلگرام تنظیم نشده یا فرمت آن اشتباه است: {e}")
    exit()

IRAN_TIMEZONE = pytz.timezone('Asia/Tehran')

# ... (توابع کمکی بدون تغییر) ...
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
rubika_client: Client | None = None
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

# ===============================================================
# پردازشگر اصلی پیام‌ها (Worker Logic)
# ===============================================================
async def process_event(event, event_type):
    global stats, message_map
    if not rubika_client: return

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
            caption = message.text or ""
            sent_rubika_message = None
            message_type = "unknown"
            file_path = None

            if message.media and isinstance(message.media, telethon_types.MessageMediaPoll):
                message_type = "poll (as text)"
                poll = message.media.poll
                question = poll.question
                options = "\n".join([f"- {answer.text}" for answer in poll.answers])
                poll_text = f"📊 نظرسنجی: {question}\n\n{options}"
                sent_rubika_message = await rubika_client.send_message(destination_guid, poll_text, reply_to_message_id=rubika_reply_to_id)
            elif message.geo:
                message_type = "location"
                geo = message.geo
                location_text = f"📍 موقعیت مکانی:\nLat: {geo.lat}, Long: {geo.long}"
                sent_rubika_message = await rubika_client.send_message(destination_guid, location_text, reply_to_message_id=rubika_reply_to_id)
            elif message.contact:
                message_type = "contact"
                contact = message.contact
                contact_text = f"👤 مخاطب:\nنام: {contact.first_name} {contact.last_name or ''}\nشماره: {contact.phone_number}"
                sent_rubika_message = await rubika_client.send_message(destination_guid, contact_text, reply_to_message_id=rubika_reply_to_id)
            elif message.text and not message.media:
                message_type = "text"
                sent_rubika_message = await rubika_client.send_message(destination_guid, message.text, reply_to_message_id=rubika_reply_to_id)
            
            elif message.photo:
                message_type = "photo"
                file_path = await user_client.download_media(message.photo, file="downloads/")
                sent_rubika_message = await rubika_client.send_photo(destination_guid, photo=InputPhoto(file_path), caption=caption, reply_to_message_id=rubika_reply_to_id)
            elif message.video:
                message_type = "video"
                file_path = await user_client.download_media(message.video, file="downloads/")
                sent_rubika_message = await rubika_client.send_video(destination_guid, video=InputVideo(file_path), caption=caption, reply_to_message_id=rubika_reply_to_id)
            elif message.audio:
                message_type = "audio"
                file_path = await user_client.download_media(message.audio, file="downloads/")
                sent_rubika_message = await rubika_client.send_music(destination_guid, music=InputMusic(file_path), caption=caption, reply_to_message_id=rubika_reply_to_id)
            elif message.voice:
                message_type = "voice"
                file_path = await user_client.download_media(message.voice, file="downloads/")
                sent_rubika_message = await rubika_client.send_voice(destination_guid, voice=InputVoice(file_path), reply_to_message_id=rubika_reply_to_id)
            elif message.document:
                message_type = "document"
                file_path = await user_client.download_media(message.document, file="downloads/")
                sent_rubika_message = await rubika_client.send_file(destination_guid, file=InputFile(file_path), caption=caption, reply_to_message_id=rubika_reply_to_id)

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
    
    # ... (بقیه توابع بدون تغییر) ...
    elif event_type == "edited":
        edited_message = event.message
        print(f"\n[پردازش ویرایش پیام] شناسه: {edited_message.id}")
        telegram_id = str(edited_message.id)
        mapping = message_map.get(telegram_id)
        if mapping:
            rubika_id = mapping["rubika_id"]
            destination_guid = mapping["destination_id"]
            new_content = edited_message.text or ""
            await rubika_client.edit_message(destination_guid, rubika_id, new_content)
            print(f"-> پیام ({rubika_id}) در روبیکا ({destination_guid}) ویرایش شد.")
    
    elif event_type == "deleted":
        print(f"\n[پردازش حذف پیام] شناسه‌ها: {event.deleted_ids}")
        try:
            to_delete_in_rubika = {}
            for deleted_id in event.deleted_ids:
                telegram_id = str(deleted_id)
                if telegram_id in message_map:
                    mapping = message_map[telegram_id]
                    rubika_id = mapping["rubika_id"]
                    destination_guid = mapping["destination_id"]
                    if destination_guid not in to_delete_in_rubika:
                        to_delete_in_rubika[destination_guid] = []
                    to_delete_in_rubika[destination_guid].append(rubika_id)
                    del message_map[telegram_id]
            
            for guid, msg_ids in to_delete_in_rubika.items():
                await rubika_client.delete_messages(guid, msg_ids)
                print(f"-> تعداد {len(msg_ids)} پیام در روبیکا ({guid}) حذف شدند.")

            save_data_to_file('message_map.json', message_map)
        except Exception as e:
            print(f"!! خطا در پردازش حذف پیام: {e}")

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
        status_text = "✅ ربات فعال و در حال کار است.\n\n**— نقشه مسیردهی فعال —**\n"
        for tg_id, rb_id in routing_map.items(): status_text += f"`{tg_id}` ➡️ `{rb_id}`\n"
        await event.respond(status_text, parse_mode='markdown')
    elif command == "/clearstats" or "پاک کردن آمار" in command:
        stats = get_default_stats()
        save_data_to_file('stats.json', stats)
        await event.respond("🗑 آمار ربات با موفقیت پاک و صفر شد.")

# ===============================================================
# تابع اصلی برنامه (main)
# ===============================================================
async def main(event_queue):
    global user_client, bot_client, rubika_client, routing_map, message_map, stats
    
    pairs = CHANNEL_MAP_STR.split(','); [routing_map.update({int(p.split(':', 1)[0].strip()): p.split(':', 1)[1].strip()}) for p in pairs if ':' in p]
    source_channel_ids = list(routing_map.keys())
    
    message_map = load_data_from_file('message_map.json', {}); stats = load_data_from_file('stats.json', get_default_stats())
    if not os.path.exists("downloads"): os.makedirs("downloads")

    print("در حال اتصال کلاینت‌ها...")
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    bot_client = TelegramClient('bot_session', API_ID, API_HASH)
    
    rubika_client = Client("my_account")
    
    await rubika_client.start()

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
    print("کلاینت‌های تلگرام با موفقیت آنلاین شدند.")
    
    me = await rubika_client.get_me()
    print(f"کلاینت روبیکا با موفقیت به عنوان {me.first_name} آنلاین شد.")
    
    await send_admin_notification("✅ ربات فورواردر (حالت سلف) با موفقیت آنلاین شد و آماده دریافت پیام است.")
    
    await asyncio.gather(user_client.run_until_disconnected(), bot_client.run_until_disconnected())
