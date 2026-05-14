with open("vk_music_backend.py", "r") as f:
    lines = f.readlines()

with open("vk_music_backend.py", "w") as f:
    for line in lines:
        if line.strip() == "from __future__ import annotations":
            pass
        elif line.strip() == "\"\"\"VK-first music backend with FastAPI and shared aggregation logic.\"\"\"":
            f.write("from __future__ import annotations\n")
            f.write(line)
        else:
            f.write(line)
