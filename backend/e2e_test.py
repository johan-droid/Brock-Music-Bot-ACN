import asyncio
import sys
import time

import app.config_loader as c
from app.core.userbot import _build_client_from_session

BOT = "@brookmusicbotACN_bot"


async def main():
    entry = c.config.userbot_auth_entries[0]
    client = _build_client_from_session(1, entry)
    await client.start()

    me = await client.get_me()
    print("userbot:", me.first_name, me.id)

    args = sys.argv[1:]
    for text in args:
        print(f"\n>>> SENDING: {text}")
        try:
            sent = await client.send_message(BOT, text)
            print("sent msg id:", sent.id)
        except Exception as e:
            print("send failed:", type(e).__name__, e)
            continue

        # wait for a reply
        for _ in range(15):
            await asyncio.sleep(1)
            try:
                async for msg in client.get_chat_history(BOT, limit=2):
                    if msg.reply_to_message_id == sent.id:
                        print("REPLY:", (msg.text or msg.caption or "")[:400])
                        break
                else:
                    continue
                break
            except Exception as e:
                print("history err:", e)
                break
        else:
            print("NO REPLY in 15s")

    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
