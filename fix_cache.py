import re

with open("bot/utils/cache.py", "r") as f:
    content = f.read()

content = content.replace("await sqlite_cache.set(key, str(current))", "if sqlite_cache: await sqlite_cache.set(key, str(current))")
content = content.replace("await sqlite_cache.expire(key, seconds)", "if sqlite_cache: await sqlite_cache.expire(key, seconds)")
content = content.replace("await sqlite_cache.delete(key)", "if sqlite_cache: await sqlite_cache.delete(key)")

with open("bot/utils/cache.py", "w") as f:
    f.write(content)
