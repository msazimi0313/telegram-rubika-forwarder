import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from rubpy import BotClient
from flask import Flask
from threading import Thread

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    API_ID = int(os.environ.get("TELEGRAM_API_ID"))
    API_HASH = os.environ.get("TELEGRAM_API_HASH")
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی ضروری تنظیم نشده است.")
    exit()

PORT = int(os.environ.get("PORT", 10000))

# ===============================================================
# بخش وب سرور Flask (برای بیدار نگه داشتن ربات)
# ===============================================================
app = Flask(__name__)

@app.route('/')
def hello_world():
    return "ربات فورواردر فعال است."

# ===============================================================
# بخش اصلی کد ربات
# ===============================================================

telegram_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
routing_map = {}
message_map = {}

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

@telegram_client.on(events.NewMessage)
async def handle_new_message(event):
    message = event.message
    # Telethon chat_id is negative for channels, we need to add the -100 prefix back
    source_id = int(f"-100{message.chat_id}")
    destination_id = routing_map.get(source_id)

    if not destination_id: return

    print(f"\nپیام جدید از کانال تلگرام ({source_id}) -> ارسال به روبیکا ({destination_id})")
    try:
        sent_rubika_message = None
        caption = message.text or "" # In Telethon, caption is part of message.text for media

        if message.text and not message.media:
            sent_rubika_message = await rubika_bot.send_message(destination_id, message.text)
        elif message.photo or message.video or message.document:
            print("فایل شناسایی شد. در حال دانلود...")
            # Using a temporary file name
            file_path = await message.download_media(file=f"temp_{message.id}")
            print(f"فایل در '{file_path}' دانلود شد. در حال آپلود به روبیکا...")
            
            file_type = 'Image' if message.photo else ('Video' if message.video else 'File')
            
            sent_rubika_message = await rubika_bot.send_file(
                destination_id,
                file=file_path,
                text=caption,
                type=file_type
            )
            os.remove(file_path)

        if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
            message_map[message.id] = sent_rubika_message.message_id
            save_data_to_file('message_map.json', message_map)
            print(f"--> فوروارد با موفقیت انجام و شناسه ها ثبت شد.")
        
    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")

@telegram_client.on(events.MessageDeleted)
async def handle_deleted_message(event):
    for msg_id in event.deleted_ids:
        if msg_id in message_map:
            rubika_id = message_map.pop(msg_id)
            save_data_to_file('message_map.json', message_map)
            
            # This logic needs improvement to find the correct destination channel
            # For now, we assume the first channel in the map
            first_destination = next(iter(routing_map.values()))
            
            print(f"پیام حذف شده تلگرام ({msg_id}) شناسایی شد. در حال حذف پیام ({rubika_id}) در روبیکا...")
            try:
                await rubika_bot.delete_messages(first_destination, [rubika_id])
                print(f"--> پیام ({rubika_id}) با موفقیت در روبیکا حذف شد.")
            except Exception as e:
                print(f"!! یک خطا در هنگام حذف پیام در روبیکا رخ داد: {e}")

async def run_telethon_client():
    global message_map, routing_map
    
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if ':' in pair:
                tg_id, rb_id = pair.split(':', 1)
                routing_map[int(tg_id.strip())] = rb_id.strip()
        if not routing_map: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش CHANNEL_MAP: {e}")
        return

    message_map = load_data_from_file('message_map.json', {})
    
    print("در حال اتصال کلاینت روبیکا...")
    await rubika_bot.start()
    
    print("ربات فورواردر (نسخه Telethon) آنلاین شد. منتظر پیام...")
    await telegram_client.run_until_disconnected()

# --- بخش نهایی: اجرای همزمان وب سرور و ربات ---
def run_flask_app():
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    # اجرای وب سرور در یک ترد جداگانه
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    
    print("وب سرور Flask فعال شد. در حال راه اندازی کلاینت تلگرام...")
    # اجرای کلاینت تلگرام
    with telegram_client:
        telegram_client.loop.run_until_complete(run_telethon_client())
