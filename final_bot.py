import asyncio
import os
import json
from datetime import datetime
import pytz
import jdatetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession # <-- ایمپورت جدید
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

# *** تغییر اصلی اینجاست: استفاده از StringSession ***
# ما به جای ارسال مستقیم رشته، آن را در کلاس StringSession قرار می دهیم
telegram_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

rubika_bot = BotClient(RUBIKA_BOT_TOKEN)
routing_map = {}
message_map = {}

# ... (بقیه توابع شما دقیقاً مثل قبل است و نیازی به تغییر ندارد)

# (کد کامل بقیه توابع در اینجا قرار می گیرد)

async def main():
    # ... (بقیه تابع main بدون تغییر)

if __name__ == '__main__':
    # ... (این بخش هم بدون تغییر)
