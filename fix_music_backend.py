import re

with open("bot/core/music_backend.py", "r") as f:
    content = f.read()

# Replace hardcoded sorted_sources fallback arrays
content = re.sub(
    r'sorted_sources = \["youtube_wrapper", "youtube",\s*"jiosaavn_wrapper", "jiosaavn"\]',
    'sorted_sources = ["vk", "deezer"]',
    content, flags=re.DOTALL
)

with open("bot/core/music_backend.py", "w") as f:
    f.write(content)
