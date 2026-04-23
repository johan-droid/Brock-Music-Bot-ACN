# Soul King Mini App Build Package

This package keeps the existing bot/backend intact and adds a dedicated mini app backend surface.

## Proposed structure

```text
Music bot/
├── mini_app_backend/
│   ├── __init__.py
│   ├── app.py
│   ├── auth.py
│   ├── dependencies.py
│   ├── schemas.py
│   ├── settings.py
│   ├── realtime/
│   │   ├── __init__.py
│   │   └── socket_server.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── lobby.py
│   │   ├── search.py
│   │   ├── sessions.py
│   │   └── stream.py
│   └── services/
│       ├── __init__.py
│       ├── lobby_service.py
│       └── music_service.py
├── docs/
│   └── mini_app/
│       ├── 01_FOLDER_STRUCTURE.md
│       ├── 02_DATABASE_SCHEMA.sql
│       ├── 03_API_SOCKET_CONTRACTS.md
│       └── 04_TWO_WEEK_PLAN.md
├── bot/...
├── vk_music_backend.py
└── .env.example
```

## Frontend workspace recommendation

Keep frontend as a separate deployable app (`soul-king-mini-frontend`) to publish to Cloudflare Pages:

```text
soul-king-mini-frontend/
├── src/
│   ├── app/
│   │   ├── pages/
│   │   │   ├── HomePage.tsx
│   │   │   ├── SearchPage.tsx
│   │   │   ├── LobbyPage.tsx
│   │   │   └── PlayerPage.tsx
│   │   ├── stores/
│   │   │   ├── playbackStore.ts
│   │   │   ├── lobbyStore.ts
│   │   │   └── searchStore.ts
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── contracts.ts
│   │   ├── sockets/
│   │   │   └── lobbySocket.ts
│   │   ├── components/
│   │   └── styles/
│   │       └── telegram-theme.css
│   ├── main.tsx
│   └── index.css
├── tailwind.config.ts
├── postcss.config.cjs
├── package.json
└── vite.config.ts
```

## Integration points already wired

- `mini_app_backend/services/music_service.py` reuses `bot/core/music_backend.py`.
- `mini_app_backend/services/lobby_service.py` reuses `QueueManager` + cache.
- `mini_app_backend/auth.py` validates Telegram `initData` with HMAC-SHA256.
- `mini_app_backend/realtime/socket_server.py` defines lobby Socket.IO events.

## Run command

```bash
uvicorn mini_app_backend:app --host 0.0.0.0 --port $PORT
```

