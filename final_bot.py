import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from rubpy import BotClient

# ... (بخش تنظیمات و متغیرهای محیطی مثل قبل بدون تغییر باقی می‌ماند) ...
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

# ... (توابع کمکی مثل get_default_stats, load_data, save_data مثل قبل) ...
def get_default_stats():
    return {"total_forwarded": 0, "by_type": {}, "errors": 0, "last_activity_time": None}

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

# این متغیرها به صورت سراسری استفاده خواهند شد
user_client: TelegramClient | None = None
bot_client: TelegramClient | None = None
rubika_bot: BotClient | None = None
routing_map = {}
message_map = {}
stats = {}

# ===============================================================
# پردازشگر اصلی پیام‌ها (Worker Logic)
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
        
        # --- پیاده‌سازی قابلیت ریپلای ---
        rubika_reply_to_id = None
        if message.is_reply:
            telegram_reply_to_id = str(message.reply_to_message_id)
            if telegram_reply_to_id in message_map:
                rubika_reply_to_id = message_map[telegram_reply_to_id].get("rubika_id")
                print(f"-> پیام ریپلای است. شناسه روبیکا: {rubika_reply_to_id}")

        try:
            caption = message.text or ""
            sent_rubika_message = None
            message_type = "unknown"
            file_path = None

            # ... (منطق ارسال انواع پیام مثل قبل، با یک تغییر کوچک) ...
            # در تمام متدهای ارسال، پارامتر reply_to_message_id را اضافه می‌کنیم
            
            if message.text and not message.media:
                message_type = "text"
                sent_rubika_message = await rubika_bot.send_message(destination_id, message.text, reply_to_message_id=rubika_reply_to_id)
            elif message.photo:
                message_type = "photo"
                print("--> در حال دانلود عکس...")
                file_path = await user_client.download_media(message.photo, file="downloads/")
                sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='Image', reply_to_message_id=rubika_reply_to_id)
            # ... (برای ویدیو، فایل و صدا هم به همین شکل reply_to_message_id اضافه می‌شود) ...

            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            
            if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
                # ... (منطق ذخیره آمار و message_map مثل قبل) ...
                telegram_id = str(message.id)
                rubika_id = sent_rubika_message.message_id
                message_map[telegram_id] = {"rubika_id": rubika_id, "destination_id": destination_id}
                save_data_to_file('message_map.json', message_map)
                # ...
                print("-> پیام با موفقیت ارسال و مپ شد.")

        except Exception as e:
            print(f"!! خطا در پردازش پیام جدید: {e}")
            # ... (منطق ثبت خطا مثل قبل)
    
    elif event_type == "edited":
        # ... (منطق ویرایش پیام مثل قبل) ...
        pass
    
    elif event_type == "deleted":
        print(f"\n[پردازش حذف پیام] شناسه‌ها: {event.deleted_ids}")
        try:
            for deleted_id in event.deleted_ids:
                telegram_id = str(deleted_id)
                if telegram_id in message_map:
                    mapping = message_map[telegram_id]
                    rubika_id = mapping["rubika_id"]
                    destination_id = mapping["destination_id"]
                    await rubika_bot.delete_messages(destination_id, [rubika_id])
                    print(f"-> پیام متناظر ({rubika_id}) در روبیکا ({destination_id}) حذف شد.")
                    del message_map[telegram_id]
            save_data_to_file('message_map.json', message_map)
        except Exception as e:
            print(f"!! خطا در پردازش حذف پیام: {e}")

# ===============================================================
# تابع اصلی برنامه (main)
# ===============================================================
async def main(event_queue):
    global user_client, bot_client, rubika_bot, routing_map, message_map, stats
    
    # ... (بارگذاری نقشه کانال‌ها، آمار و message_map مثل قبل) ...
    # ... (ساخت پوشه downloads مثل قبل) ...
    
    print("در حال اتصال کلاینت‌ها...")
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    bot_client = TelegramClient('bot_session', API_ID, API_HASH)
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()

    # --- هندلرهای جدید که فقط رویداد را به صف اضافه می‌کنند ---
    source_channel_ids = list(routing_map.keys())
    
    @user_client.on(events.NewMessage(chats=source_channel_ids))
    async def new_message_handler(event):
        await event_queue.put(("new", event))

    @user_client.on(events.MessageEdited(chats=source_channel_ids))
    async def edited_message_handler(event):
        await event_queue.put(("edited", event))

    @user_client.on(events.MessageDeleted(chats=source_channel_ids))
    async def deleted_message_handler(event):
        await event_queue.put(("deleted", event))
    
    # ... (هندلر دستورات ادمین مثل قبل) ...

    print("ربات آماده به کار است...")
    await user_client.start()
    await bot_client.start(bot_token=TELEGRAM_BOT_TOKEN)
    
    print("کلاینت‌های تلگرام با موفقیت آنلاین شدند.")
    
    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )
