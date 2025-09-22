def main():
    global routing_map, source_channel_ids
    try:
        pairs = CHANNEL_MAP_STR.split(',')
        for pair in pairs:
            if ':' in pair:
                tg_id, rb_id = pair.split(':', 1)
                routing_map[int(tg_id.strip())] = rb_id.strip()
        source_channel_ids = list(routing_map.keys())
        if not source_channel_ids: raise ValueError("نقشه کانال ها خالی است.")
    except Exception as e:
        print(f"خطا در پردازش CHANNEL_MAP: {e}")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    admin_filter = filters.User(user_id=TELEGRAM_ADMIN_IDS)
    
    app.add_handler(CommandHandler("admin", admin_panel, filters=admin_filter))
    app.add_handler(CommandHandler("status", admin_status, filters=admin_filter))

    # --- بخش اصلاح شده ---
    # فیلتر آمار را با فیلتر ادمین ترکیب می‌کنیم
    stats_combined_filter = ((filters.COMMAND & filters.Regex('^/stats$')) | (filters.TEXT & filters.Regex('^📊 آمار$'))) & admin_filter
    app.add_handler(MessageHandler(stats_combined_filter, admin_stats))

    # فیلتر پاک کردن آمار را با فیلتر ادمین ترکیب می‌کنیم
    clear_stats_combined_filter = ((filters.COMMAND & filters.Regex('^/clearstats$')) | (filters.TEXT & filters.Regex('^🗑 پاک کردن آمار$'))) & admin_filter
    app.add_handler(MessageHandler(clear_stats_combined_filter, admin_clear_stats))
    # --- پایان بخش اصلاح شده ---

    app.add_handler(MessageHandler(filters.COMMAND & (~admin_filter), unauthorized_user_handler))
    
    print("ربات آنلاین شد...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()
