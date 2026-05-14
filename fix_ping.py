import re

with open("bot/plugins/misc.py", "r") as f:
    content = f.read()

# Replace the ping command implementation
pattern = r'@Client.on_message\(filters.command\("ping"\) & \(filters.private \| filters.group\)\)\n@rate_limit\nasync def ping_cmd\(client: Client, message: Message\):.*?(?=@Client|\Z)'
replacement = """@Client.on_message(filters.command("ping") & (filters.private | filters.group))
@rate_limit
async def ping_cmd(client: Client, message: Message):
    \"\"\"Check bot latency and connectivity.\"\"\"
    await message.reply("Bot is alive")
"""

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open("bot/plugins/misc.py", "w") as f:
    f.write(new_content)
