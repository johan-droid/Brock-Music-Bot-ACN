echo "### Deliverable 1 & 5: bot/utils/audio_config.py"
cat bot/utils/audio_config.py

echo "### Deliverable 3: bot/utils/ffmpeg.py"
cat bot/utils/ffmpeg.py

echo "### Deliverable 1, 2, 4: bot/core/call.py"
cat bot/core/call.py | grep -E -A 100 'def _build_stream\(|def play\('
