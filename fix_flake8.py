import re

files = [
    "bot/core/music_backend.py",
    "bot/utils/circuit_breaker.py",
    "bot/platforms/youtube.py",
    "bot/platforms/youtube_wrapper.py",
    "bot/platforms/jiosaavn.py",
    "bot/platforms/jiosaavn_wrapper.py",
]

for fpath in files:
    with open(fpath, "r") as f:
        content = f.read()

    # Remove unused imports specifically flagged
    content = re.sub(r"from bot\.utils\.errors import SourceExhaustedError\n?", "", content)

    # We will ignore E501 (line length) for now as fixing it automatically can mess up string formatting

    with open(fpath, "w") as f:
        f.write(content)
