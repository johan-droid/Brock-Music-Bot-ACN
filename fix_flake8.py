with open("bot/__main__.py", "r") as f:
    content = f.read()
if "import os" not in content:
    content = content.replace("import sys", "import sys\nimport os")
with open("bot/__main__.py", "w") as f:
    f.write(content)

with open("bot/utils/health_monitor.py", "r") as f:
    content = f.read()
if "from bot.platforms.jamendo import JamendoClient" not in content:
    content = content.replace("from bot.platforms.jamendo import JAMENDO_CLIENT_ID", "from bot.platforms.jamendo import JAMENDO_CLIENT_ID, JamendoClient")
with open("bot/utils/health_monitor.py", "w") as f:
    f.write(content)
