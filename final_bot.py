import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from rubpy import BotClient

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    API_ID = int(os.environ.get("TELEGRAM_API_ID"))
    API_HASH = os.environ.get("TELEGRAM_API_HASH")
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
    
    CHANNEL_MAP_STR = os.environ.get("CHANNEL_MAP", "")
    ADMIN_IDS_STR = os.environ.get("TELEGRAM_ADMIN_ID", "")
    TELEGRAM_ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',')]
    
    RUBIKA_BOT_TOKEN = os.environ.get("RUBIKA_BOT_TOKEN")
except (TypeError, ValueError):
    print("خطا: یکی از متغیرهای محیطی تنظیم نشده است.")
    exit()

# ===============================================================
# بخش اصلی کد
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
    source_id = message.chat_id
    destination_id = routing_map.get(source_id)

    if not destination_id: return

    print(f"\nپیام جدید از کانال تلگرام ({source_id}) -> ارسال به روبیکا ({destination_id})")
    try:
        sent_rubika_message = None
        if message.text:
            sent_rubika_message = await rubika_bot.send_message(destination_id, message.text)
        elif message.photo or message.video or message.document:
            print("فایل شناسایی شد. در حال دانلود...")
            file_path = await message.download_media()
            print(f"فایل در '{file_path}' دانلود شد. در حال آپلود به روبیکا...")
            
            file_type = 'Image' if message.photo else ('Video' if message.video else 'File')
            
            sent_rubika_message = await rubika_bot.send_file(
                destination_id,
                file=file_path,
                text=message.text, # در تله تون کپشن با متن یکی است
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
            
            first_destination = next(iter(routing_map.values()))
            
            print(f"پیام حذف شده تلگرام ({msg_id}) شناسایی شد. در حال حذف پیام ({rubika_id}) در روبیکا...")
            try:
                await rubika_bot.delete_messages(first_destination, [rubika_id])
                print(f"--> پیام ({rubika_id}) با موفقیت در روبیکا حذف شد.")
            except Exception as e:
                print(f"!! یک خطا در هنگام حذف پیام در روبیکا رخ داد: {e}")

async def main():
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

if __name__ == '__main__':
    telegram_client.start()
    asyncio.run(main())
