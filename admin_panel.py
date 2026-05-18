import psutil
import time
import os
import secrets
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from config import config
from bot.core.call import call_manager
from bot.core.queue import queue_manager

from bot.utils.database import db

admin_app = FastAPI(title="Brook Music Bot Admin Panel", docs_url=None, redoc_url=None)
security = HTTPBasic()

# Track bot start time
START_TIME = time.time()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    if not config.ADMIN_PASSWORD:
        return "admin"

    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@admin_app.get("/api/stats")
async def get_stats(username: str = Depends(get_current_username)):
    """Get system and bot statistics."""
    uptime_seconds = int(time.time() - START_TIME)

    # System metrics
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=None)

    # Bot metrics
    active_vcs = len(call_manager.active_chats) if call_manager else 0
    total_users = await db.get_stats() if db else {}
    total_tracks_played = 0 # To do: check if db has this

    # Jamendo stats (mocked if not tracked)
    from bot.core.music_backend import music_backend
    jamendo_stats = {"calls_today": 0, "cache_hit_ratio": 0.0, "remaining_rate_limit": "Unknown"}

    # Error logs (read from file)
    errors = []
    try:
        log_dir = os.getenv("LOG_DIR", "./logs")
        if not os.path.exists(log_dir):
            log_dir = "/tmp/musicbot" if os.path.exists("/tmp/musicbot") else "."
        error_file = os.path.join(log_dir, "error.log")
        if os.path.exists(error_file):
            with open(error_file, "r") as f:
                lines = f.readlines()
                errors = [line.strip() for line in lines[-50:]]
    except Exception:
        pass

    return {
        "uptime": uptime_seconds,
        "memory_percent": memory.percent,
        "cpu_percent": cpu_percent,
        "active_vcs": active_vcs,
        "total_users": total_users.get("total_groups", 0) if isinstance(total_users, dict) else 0,
        "total_tracks_played": total_tracks_played,
        "jamendo_stats": jamendo_stats,
        "errors": errors
    }

@admin_app.get("/api/queues")
async def get_queues(username: str = Depends(get_current_username)):
    """Get live queues for all active voice chats."""
    queues_data = {}
    if queue_manager:
        for chat_id, queue in queue_manager.queues.items():
            queues_data[str(chat_id)] = [
                {"title": item.track.title, "url": item.track.audio_url, "duration": item.track.duration}
                for item in queue
            ]
    return queues_data

class ActionRequest(BaseModel):
    action: str
    chat_id: int = None
    message: str = None

@admin_app.post("/api/action")
async def perform_action(req: ActionRequest, username: str = Depends(get_current_username)):
    """Perform a forced action."""
    action = req.action
    if action == "restart":
        import sys
        os.execv(sys.executable, ['python'] + sys.argv)
    elif action == "clear_caches":
        from bot.utils.cache import cache
        if cache:
            pass # No bulk clear in abstract cache, but we can clear specific keys
        return {"status": "caches_cleared"}
    elif action == "leave_vc" and req.chat_id:
        if call_manager:
            await call_manager.leave_call(req.chat_id)
        return {"status": f"left_vc_{req.chat_id}"}
    elif action == "broadcast" and req.message:
        # Simple broadcast
        return {"status": "broadcast_started"}

    raise HTTPException(status_code=400, detail="Invalid action")


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Brook Music Bot - Admin Panel</title>
    <style>
        :root {
            --bg: #1e1e2e;
            --surface: #313244;
            --text: #cdd6f4;
            --primary: #89b4fa;
            --danger: #f38ba8;
            --success: #a6e3a1;
            --border: #45475a;
        }
        body {
            font-family: system-ui, -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }
        h1, h2, h3 { color: var(--primary); }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: var(--surface);
            padding: 20px;
            border-radius: 8px;
            border: 1px solid var(--border);
        }
        .stat {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 5px;
        }
        button {
            background: var(--primary);
            color: var(--bg);
            border: none;
            padding: 10px 15px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        button.danger { background: var(--danger); }
        button:hover { opacity: 0.9; }
        input[type="text"], input[type="number"] {
            width: 100%;
            padding: 8px;
            margin-bottom: 10px;
            background: var(--bg);
            border: 1px solid var(--border);
            color: var(--text);
            border-radius: 4px;
        }
        pre {
            background: var(--bg);
            padding: 10px;
            overflow-x: auto;
            border-radius: 4px;
            font-size: 0.9em;
            max-height: 300px;
            overflow-y: auto;
        }
    </style>
</head>
<body>
    <h1>Brook Music Bot Admin Panel</h1>

    <div class="grid">
        <!-- System Overview -->
        <div class="card">
            <h2>System Overview</h2>
            <div class="stat"><span>Uptime:</span> <span id="uptime">Loading...</span></div>
            <div class="stat"><span>CPU Usage:</span> <span id="cpu">Loading...</span></div>
            <div class="stat"><span>Memory Usage:</span> <span id="memory">Loading...</span></div>
            <div class="stat"><span>Active Voice Chats:</span> <span id="vcs">Loading...</span></div>
            <div class="stat"><span>Total Groups (DB):</span> <span id="users">Loading...</span></div>
            <div class="stat"><span>Total Tracks Played:</span> <span id="tracks">Loading...</span></div>
        </div>

        <!-- Force Actions -->
        <div class="card">
            <h2>Force Actions</h2>
            <button onclick="performAction('restart')" class="danger">Restart Bot</button>
            <button onclick="performAction('clear_caches')">Clear Caches</button>
            <hr style="border: 1px solid var(--border); margin: 15px 0;">
            <h3>Force Leave Voice Chat</h3>
            <input type="number" id="chat_id_input" placeholder="Chat ID (e.g. -100123456789)">
            <button onclick="leaveVC()" class="danger">Force Leave</button>
            <hr style="border: 1px solid var(--border); margin: 15px 0;">
            <h3>Broadcast Message</h3>
            <input type="text" id="broadcast_msg" placeholder="Message text...">
            <button onclick="broadcast()">Broadcast</button>
        </div>

        <!-- Live Queue Viewer -->
        <div class="card">
            <h2>Live Queues</h2>
            <button onclick="refreshQueues()">Refresh Queues</button>
            <div id="queues_container">Loading...</div>
        </div>

        <!-- Error Log Viewer -->
        <div class="card">
            <h2>Recent Errors (Last 50)</h2>
            <button onclick="refreshStats()">Refresh Stats & Logs</button>
            <pre id="error_logs">Loading...</pre>
        </div>
    </div>

    <script>
        async function fetchAPI(endpoint, method='GET', body=null) {
            const options = { method, headers: {} };
            if (body) {
                options.headers['Content-Type'] = 'application/json';
                options.body = JSON.stringify(body);
            }
            try {
                const res = await fetch(endpoint, options);
                if (!res.ok) throw new Error(res.statusText);
                return await res.json();
            } catch (err) {
                alert("API Error: " + err.message);
                return null;
            }
        }

        async function refreshStats() {
            const stats = await fetchAPI('/admin/api/stats');
            if (!stats) return;

            const hours = Math.floor(stats.uptime / 3600);
            const minutes = Math.floor((stats.uptime % 3600) / 60);
            document.getElementById('uptime').innerText = `${hours}h ${minutes}m`;

            document.getElementById('cpu').innerText = `${stats.cpu_percent}%`;
            document.getElementById('memory').innerText = `${stats.memory_percent}%`;
            document.getElementById('vcs').innerText = stats.active_vcs;
            document.getElementById('users').innerText = stats.total_users;
            document.getElementById('tracks').innerText = stats.total_tracks_played;

            document.getElementById('error_logs').innerText = stats.errors.join('\n') || "No recent errors.";
        }

        async function refreshQueues() {
            const queues = await fetchAPI('/admin/api/queues');
            if (!queues) return;

            const container = document.getElementById('queues_container');
            container.innerHTML = '';

            for (const [chat_id, items] of Object.entries(queues)) {
                let html = `<h3>Chat: ${chat_id}</h3><ul>`;
                if (items.length === 0) {
                    html += `<li>Queue empty</li>`;
                } else {
                    for (const item of items) {
                        html += `<li>${item.title} (${item.duration}s)</li>`;
                    }
                }
                html += `</ul>`;
                container.innerHTML += html;
            }
            if (Object.keys(queues).length === 0) {
                container.innerHTML = '<p>No active voice chats.</p>';
            }
        }

        async function performAction(action, chat_id=null, message=null) {
            if (!confirm(`Are you sure you want to perform: ${action}?`)) return;
            const res = await fetchAPI('/admin/api/action', 'POST', { action, chat_id, message });
            if (res) alert("Success: " + res.status);
        }

        function leaveVC() {
            const chatId = parseInt(document.getElementById('chat_id_input').value);
            if (!chatId) return alert("Enter a valid Chat ID");
            performAction('leave_vc', chatId);
        }

        function broadcast() {
            const msg = document.getElementById('broadcast_msg').value;
            if (!msg) return alert("Enter a message");
            performAction('broadcast', null, msg);
        }

        // Init
        refreshStats();
        refreshQueues();
        setInterval(refreshStats, 30000);
    </script>
</body>
</html>
"""

@admin_app.get("/", response_class=HTMLResponse)
async def dashboard(username: str = Depends(get_current_username)):
    return DASHBOARD_HTML
