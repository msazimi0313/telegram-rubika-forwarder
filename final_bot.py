async def deleted_message_handler(event: events.MessageDeleted.Event):
    """هندلر حذف پیام (نسخه اصلاح شده)"""
    if not rubika_bot: return
    print(f"\n==============================================")
    print(f"یک یا چند پیام از تلگرام حذف شد.")
    try:
        # متغیر برای جلوگیری از ذخیره مکرر فایل
        map_changed = False
        for telegram_id in event.deleted_ids:
            mapping = message_map.pop(str(telegram_id), None) # حذف از مپ و دریافت مقدار
            if mapping:
                map_changed = True
                rubika_id = mapping["rubika_id"]
                destination_id = mapping["destination_id"]
                # استفاده از نام متد صحیح: delete_message_ids
                await rubika_bot.delete_message_ids(destination_id, [rubika_id])
                print(f"--> پیام متناظر ({rubika_id}) در کانال روبیکا ({destination_id}) با موفقیت حذف شد.")
            else:
                print(f"--> شناسه پیام حذف شده ({telegram_id}) در دفترچه یافت نشد.")
        
        # فقط در صورتی که تغییری در مپ ایجاد شده، فایل را ذخیره کن
        if map_changed:
            save_data_to_file('message_map.json', message_map)
            
    except Exception as e:
        print(f"!! یک خطا در هنگام حذف پیام رخ داد: {e}")
    print(f"==============================================\n")
