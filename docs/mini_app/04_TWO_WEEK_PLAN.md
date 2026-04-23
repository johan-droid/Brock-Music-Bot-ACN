# Soul King Mini App 2-Week Plan

## Week 1: Foundation + Core Flows

### Day 1

- Apply SQL from `docs/mini_app/02_DATABASE_SCHEMA.sql`.
- Add mini app env values in Railway.
- Deploy backend service with `uvicorn mini_app_backend:app`.

Exit criteria:

- `/health` works.
- `initData` validation rejects tampered payloads.

### Day 2

- Implement frontend shell in React + TypeScript.
- Add Telegram WebApp SDK bootstrap and theme token mapping.
- Add Zustand stores: playback, lobby, search.

Exit criteria:

- App opens inside Telegram with dark/light theme sync.

### Day 3

- Implement search screen + 400ms debounce.
- Integrate `GET /api/v1/search`.
- Render source badges (VK / Deezer).

Exit criteria:

- Search response < 800ms p95 on cached query.

### Day 4

- Implement individual player screen.
- Integrate `/stream/resolve` + `/stream/proxy`.
- Add fallback handling for unsupported streams.

Exit criteria:

- Individual playback works for both VK and Deezer hits.

### Day 5

- Implement lobby screen layout.
- Connect Socket.IO and `join_lobby`.
- Render `lobby_state` snapshot (now playing, queue, participants).

Exit criteria:

- Two devices in same chat see synchronized state updates.

### Day 6

- Add lobby interactions: queue add, track change, seek.
- Broadcast events from server and reconcile versions in client.

Exit criteria:

- Queue/order and seek stay in sync under reconnect tests.

### Day 7

- Add reconnect flow: restore last lobby snapshot on app open.
- Add loading/error UX for search/stream/socket states.

Exit criteria:

- App recovers cleanly after airplane mode/offline toggles.

## Week 2: Hardening + Release

### Day 8

- Add permission checks for lobby mutation endpoints.
- Enforce admin/member rules aligned with bot permissions.

Exit criteria:

- Non-admin mutation attempts return `403`.

### Day 9

- Add observability: request logs, stream startup latency, socket reconnect counters.
- Add dashboard alerts for high 429 or stream proxy failures.

Exit criteria:

- You can detect and diagnose failures without manual reproduction.

### Day 10

- Add backend tests:
  - initData verification
  - stream proxy signature expiry
  - search response schema
  - lobby version bumps

Exit criteria:

- Core tests passing in CI.

### Day 11

- Add frontend tests:
  - store reducers/selectors
  - socket event handlers
  - route guards for auth context

Exit criteria:

- Critical UI logic covered by automated tests.

### Day 12

- Performance pass:
  - Framer Motion only with transform/opacity.
  - Audio startup time optimization.
  - Queue rendering virtualization for long lists.

Exit criteria:

- Smooth 60fps interactions on mid-tier Android device.

### Day 13

- Staging release with internal testers.
- Capture bug list and fix blockers.

Exit criteria:

- No blocker defects for launch checklist.

### Day 14

- Production rollout.
- BotFather web app button update.
- Post-launch monitoring window + rollback plan verified.

Exit criteria:

- Stable release and no severe incident in first 24 hours.

## Test checklist

- `initData` signature mismatch -> `401`.
- expired `initData` -> `401`.
- proxy URL expired signature -> `401`.
- stream proxy passes `Range` and returns `206`.
- lobby sync correctness across 2+ clients with reconnect.
- queue conflict/stale version behavior.
- fallback behavior when provider resolve fails.

