with open('bot/core/bot.py', 'r') as f:
    content = f.read()

import re
search_block = """    # Determine update method: Webhook vs Polling
    # Note: Webhooks require a 'web' process and a PORT.
    if config.WEBHOOK_URL and os.getenv("PORT"):
        # Webhook mode
        webhook_addr = f"{config.WEBHOOK_URL.rstrip('/')}{config.WEBHOOK_PATH}"
        logger.info(f"Setting webhook to: {webhook_addr}")
        await bot_client.set_webhook(
            url=webhook_addr,
            secret_token=config.WEBHOOK_SECRET,
            max_connections=int(os.getenv("WEBHOOK_MAX_CONNECTIONS", "40")),
            drop_pending_updates=True
        )
        webhook_info = await bot_client.get_webhook_info()
        logger.info(f"Webhook status: {webhook_info}")
        # In webhook mode, we only CONNECT the client, we don't START polling
        await bot_client.connect()
        logger.info("Bot connected in WEBHOOK mode.")
    else:
        # Polling mode: Ensure no stale webhooks exist
        if config.WEBHOOK_URL and not os.getenv("PORT"):
            logger.warning("WEBHOOK_URL is set but no PORT found (Worker mode). Falling back to POLLING.")

        try:
            await bot_client.delete_webhook()
            logger.info("Stale webhooks cleared.")
        except Exception:
            pass
        await bot_client.start()
        logger.info("Bot started in POLLING mode (Worker).")"""

replace_block = """    # Webhook mode is unsupported with Pyrogram; always use polling
    try:
        await bot_client.delete_webhook()
    except Exception:
        pass
    await bot_client.start()
    logger.info("Bot started in POLLING mode.")"""

new_content = content.replace(search_block, replace_block)

if new_content != content:
    print("Replacement successful")
    with open('bot/core/bot.py', 'w') as f:
        f.write(new_content)
else:
    print("Replacement failed")
