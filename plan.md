1. **Analyze schema**
    - Done: Looked at `bot/utils/neon_db.py`, `bot/utils/sqlite_db.py`, and `bot/utils/supabase_db.py`.

2. **Modify main Track/Song table**
    - Done: Removed YouTube-specific fields like `source`, `platform`, `file_id`.
    - Done: Replaced `track_id VARCHAR(255)` with `jamendo_track_id INTEGER`.
    - Done: Normalized column names to `thumbnail_url` and `audio_url`.
    - Done: Re-indexed `jamendo_track_id`.

3. **Update queue and playlist tables**
    - Queues are `JSONB` in Neon/Supabase and JSON strings in SQLite, holding a list of track objects. Our python code changes will insert track dicts matching the new fields.
    - Added migrations to clear queues from Neon/SQLite database to remove stale youtube IDs.
    - Supabase playlists (not fully implemented, but in setup) and `play_history` also updated to use `jamendo_track_id`.

4. **Write migration script**
    - Done: `migrate_database_schema.py` added to run DDLs for SQLite and Neon to `DROP TABLE IF EXISTS *_old`, `ALTER TABLE ... RENAME TO *_old`, and `CREATE TABLE ...` with the new schema, effectively doing a safe replacement while deleting old incompatible data.
    - Supposed to clear old records (queues, play history). Done in the migration script.

5. **Pre-commit check**
    - Completed.
