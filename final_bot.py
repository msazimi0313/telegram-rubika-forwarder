import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from rubpy import BotClient
import nest_asyncio

nest_asyncio.apply()

# ===============================================================
# بخش تنظیمات
# ===============================================================
try:
    # --- متغیرهای جدید برای Telethon ---
    API_ID = int(os.environ.get("TELEGRAM_API_ID"))
    API_HASH = os.environ.get("TELEGRAM_API_HASH")
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")

    # --- متغیرهای قبلی ---
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
# بخش اصلی کد
# ===============================================================

# --- کلاینت‌ها ---
user_client: TelegramClient | None = None # کلاینت اصلی برای خواندن کانال‌ها
bot_client: TelegramClient | None = None  # کلاینت ربات برای پنل ادمین
rubika_bot: BotClient | None = None

# --- دیکشنری‌ها و آمار ---
routing_map = {}
source_channel_ids = []
message_map = {}
stats = {}

def get_default_stats():
    return {
        "total_forwarded": 0,
        "by_type": {"text": 0, "photo": 0, "video": 0, "document": 0, "audio": 0, "voice": 0},
        "errors": 0,
        "last_activity_time": None
    }

def load_data_from_file(filename, default_data):
    try:
        with open(filename, 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data_to_file(filename, data):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

async def send_admin_notification(text):
    if bot_client:
        for admin_id in TELEGRAM_ADMIN_IDS:
            try:
                await bot_client.send_message(admin_id, text, parse_mode='markdown')
            except Exception as e:
                print(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")

# ===============================================================
# هندلرهای رویدادهای تلگرام (با Telethon)
# ===============================================================

async def new_message_handler(event):
    global stats, message_map
    message = event.message
    if not rubika_bot: return

    source_id = message.chat_id
    destination_id = routing_map.get(source_id)
    if not destination_id: return

    print(f"\n==============================================")
    print(f"پیام جدید از کانال تلگرام ({source_id}) -> ارسال به روبیکا ({destination_id})")
    
    try:
        caption = message.text or ""
        sent_rubika_message = None
        message_type = "unknown"
        file_path = None

        if message.text and not message.media:
            message_type = "text"
            sent_rubika_message = await rubika_bot.send_message(destination_id, message.text)
        
        elif message.photo:
            message_type = "photo"
            print("--> در حال دانلود عکس...")
            file_path = await user_client.download_media(message.photo, file="downloads/")
            sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='Image')
        
        elif message.video:
            message_type = "video"
            file_size_mb = message.video.size / 1024 / 1024
            print(f"--> در حال دانلود ویدیو ({file_size_mb:.2f} MB)...")
            file_path = await user_client.download_media(message.video, file="downloads/")
            sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='Video')

        elif message.audio:
            message_type = "audio"
            file_size_mb = message.audio.size / 1024 / 1024
            print(f"--> در حال دانلود موزیک ({file_size_mb:.2f} MB)...")
            caption = f"🎵 {message.audio.attributes[0].performer or ''} - {message.audio.attributes[0].title or ''}\n\n{caption}".strip()
            file_path = await user_client.download_media(message.audio, file="downloads/")
            sent_rubika_message = await rubika_bot.send_music(destination_id, file=file_path, text=caption)

        elif message.voice:
            message_type = "voice"
            print("--> در حال دانلود ویس...")
            file_path = await user_client.download_media(message.voice, file="downloads/")
            sent_rubika_message = await rubika_bot.send_voice(destination_id, file=file_path)

        elif message.document:
            message_type = "document"
            file_size_mb = message.document.size / 1024 / 1024
            print(f"--> در حال دانلود فایل ({file_size_mb:.2f} MB)...")
            file_path = await user_client.download_media(message.document, file="downloads/")
            sent_rubika_message = await rubika_bot.send_file(destination_id, file=file_path, text=caption, type='File')

        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            print(f"--> فایل موقت ({file_path}) حذف شد.")
            
        if message_type != "unknown":
            print(f"--> پیام از نوع '{message_type}' با موفقیت به روبیکا ارسال شد.")
            if sent_rubika_message and hasattr(sent_rubika_message, 'message_id'):
                telegram_id = message.id
                rubika_id = sent_rubika_message.message_id
                message_map[str(telegram_id)] = {"rubika_id": rubika_id, "destination_id": destination_id, "chat_id": source_id}
                save_data_to_file('message_map.json', message_map)
                
                stats["by_type"].setdefault(message_type, 0)
                stats["by_type"][message_type] += 1
                stats["total_forwarded"] += 1
                stats["last_activity_time"] = datetime.now(IRAN_TIMEZONE).isoformat()
                save_data_to_file('stats.json', stats)
        else:
            print("--> پیام از نوع پشتیبانی نشده (نظرسنجی، استیکر و...) و نادیده گرفته شد.")

    except Exception as e:
        print(f"!! یک خطا در هنگام فوروارد کردن پیام رخ داد: {e}")
        stats["errors"] = stats.get("errors", 0) + 1
        save_data_to_file('stats.json', stats)
        error_text = f"❌ خطا در فوروارد از `{source_id}`:\n\n`{e}`"
        await send_admin_notification(error_text)
    
    print(f"==============================================\n")

async def edited_message_handler(event):
    edited_message = event.message
    if not (edited_message and rubika_bot): return
    
    print(f"\n==============================================")
    print(f"یک پیام ویرایش شده از تلگرام دریافت شد.")
    try:
        telegram_id = str(edited_message.id)
        mapping = message_map.get(telegram_id)
        if mapping:
            rubika_id = mapping["rubika_id"]
            destination_id = mapping["destination_id"]
            new_content = edited_message.text or ""
            await rubika_bot.edit_message_text(destination_id, rubika_id, new_content)
            print(f"--> پیام ({rubika_id}) در کانال ({destination_id}) با موفقیت ویرایش شد.")
        else:
            print("--> شناسه پیام ویرایش شده در دفترچه یافت نشد.")
    except Exception as e:
        print(f"!! یک خطا در هنگام ویرایش پیام رخ داد: {e}")
    print(f"==============================================\n")

async def deleted_message_handler(event):
    if not rubika_bot: return

    print(f"\n==============================================")
    print(f"{len(event.deleted_ids)} پیام حذف شده از تلگرام دریافت شد.")
    try:
        for deleted_id in event.deleted_ids:
            telegram_id = str(deleted_id)
            mapping = message_map.get(telegram_id)
            if mapping:
                rubika_id = mapping["rubika_id"]
                destination_id = mapping["destination_id"]
                await rubika_bot.delete_messages(destination_id, [rubika_id])
                print(f"--> پیام متناظر ({rubika_id}) در کانال روبیکا ({destination_id}) حذف شد.")
                del message_map[telegram_id] # از مپ هم حذف میکنیم
            else:
                print(f"--> پیام حذف شده با شناسه {telegram_id} در دفترچه یافت نشد.")
        save_data_to_file('message_map.json', message_map)
    except Exception as e:
        print(f"!! یک خطا در هنگام حذف پیام رخ داد: {e}")
    print(f"==============================================\n")

# ===============================================================
# هندلرهای دستورات ادمین (از طریق ربات تلگرام)
# ===============================================================

async def admin_command_handler(event):
    global stats  # <---【تغییر اصلی】 این خط به اینجا منتقل شد
    
    command = event.raw_text.lower()
    user_id = event.sender_id
    
    if user_id not in TELEGRAM_ADMIN_IDS:
        user = await event.get_sender()
        await event.respond(f" سلام {user.first_name} عزیز! 🌸\n\nمتاسفانه شما اجازه استفاده از این دستورات را ندارید.")
        return

    if command == "/start" or command == "/admin":
        await event.respond("پنل مدیریت:", buttons=[
            ["📊 آمار (/stats)"], 
            ["⚙️ وضعیت ربات (/status)"], 
            ["🗑 پاک کردن آمار (/clearstats)"]
        ])
    
    elif command == "/stats" or "آمار" in command:
        last_time_str = "هنوز فعالیتی ثبت نشده"
        if stats.get("last_activity_time"):
            last_time_iso = datetime.fromisoformat(stats['last_activity_time'])
            jalali_time = jdatetime.datetime.fromgregorian(datetime=last_time_iso)
            last_time_str = jalali_time.strftime('%Y/%m/%d - %H:%M:%S')

        stats_text = (
            f"📊 **آمار عملکرد ربات فورواردر**\n\n"
            f"🔹 **کل پیام‌های فوروارد شده:** {stats.get('total_forwarded', 0)}\n"
            f"🔸 **آخرین فعالیت:** {last_time_str}\n"
            f"🔺 **تعداد خطاها:** {stats.get('errors', 0)}\n\n"
            f"📦 **تفکیک نوع پیام:**\n"
        )
        for msg_type, count in stats.get("by_type", {}).items():
            stats_text += f"  - `{msg_type}`: {count}\n"
        await event.respond(stats_text, parse_mode='markdown')

    elif command == "/status" or "وضعیت" in command:
        status_text = "✅ ربات فعال و در حال کار است.\n\n"
        status_text += "**— نقشه مسیردهی فعال —**\n"
        for tg_id, rb_id in routing_map.items():
            status_text += f"`{tg_id}` ➡️ `{rb_id}`\n"
        await event.respond(status_text, parse_mode='markdown')

    elif command == "/clearstats" or "پاک کردن آمار" in command:
        # 'global stats' از اینجا حذف شد چون به بالای تابع منتقل شده
        stats = get_default_stats()
        save_data_to_file('stats.json', stats)
        await event.respond("🗑 آمار ربات با موفقیت پاک و صفر شد.")

# ===============================================================
# تابع اصلی و اجرای برنامه
# ===============================================================

async def main():
    global routing_map, source_channel_ids, message_map, stats
    global user_client, bot_client, rubika_bot
    
    # --- بارگذاری نقشه کانال‌ها ---
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if ':' in pair:
                tg_id, rb_id = pair.split(':', 1)
                tg_id_int = int(tg_id.strip())
                routing_map[tg_id_int] = rb_id.strip()
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
        print("نقشه مسیردهی با موفقیت بارگذاری شد:", routing_map)
    except Exception as e:
        print(f"خطا در پردازش متغیر محیطی CHANNEL_MAP: {e}")
        return

    # --- بارگذاری داده‌های ذخیره شده ---
    message_map = load_data_from_file('message_map.json', {})
    stats = load_data_from_file('stats.json', get_default_stats())
    
    # --- ساخت پوشه دانلودها ---
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    # --- اتصال کلاینت‌ها ---
    print("در حال اتصال کلاینت کاربری تلگرام (User Client)...")
    # <---【تغییر اصلی】: استفاده مستقیم از StringSession در اینجا
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    
    print("در حال اتصال کلاینت ربات تلگرام (Bot Client)...")
    bot_client = TelegramClient('bot_session', API_ID, API_HASH)
    
    print("در حال ساخت و فعال سازی کلاینت روبیکا...")
    rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
    await rubika_bot.start()
    print("کلاینت روبیکا با موفقیت فعال شد.")

    # --- ثبت هندلرها ---
    user_client.add_event_handler(new_message_handler, events.NewMessage(chats=source_channel_ids, incoming=True))
    user_client.add_event_handler(edited_message_handler, events.MessageEdited(chats=source_channel_ids, incoming=True))
    user_client.add_event_handler(deleted_message_handler, events.MessageDeleted(chats=source_channel_ids))
    bot_client.add_event_handler(admin_command_handler, events.NewMessage(from_users=TELEGRAM_ADMIN_IDS, incoming=True))
    
    print("\n==================================================")
    print("ربات فورواردر (نسخه Telethon) در حال آنلاین شدن...")
    print("==================================================")
    
    # --- اجرای کلاینت‌ها ---
    await user_client.start()
    print("کلاینت کاربری با موفقیت متصل و آنلاین شد.")
    
    await bot_client.start(bot_token=TELEGRAM_BOT_TOKEN)
    print("کلاینت ربات با موفقیت متصل و آنلاین شد.")
    
    await send_admin_notification("✅ ربات چندکاناله (نسخه Telethon) با موفقیت آنلاین شد.")
    
    # --- اجرای همزمان و منتظر ماندن ---
    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nربات با دستور کاربر متوقف شد.")

