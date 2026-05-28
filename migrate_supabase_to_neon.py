#!/usr/bin/env python3
"""Migrate bot data from Supabase to Neon (current schema)."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("supabase_to_neon_migrate")


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _stable_int(seed: str) -> int:
    digest = hashlib.sha1((seed or "music-bot").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) & 0x7FFFFFFF


def _json_text(value: Any, default: Any) -> str:
    if value is None:
        return json.dumps(default)
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps(default)
    return json.dumps(value)


def _missing_table_error(exc: Exception) -> bool:
    text = str(exc).lower()
    needles = ("pgrst205", "42p01", "does not exist", "could not find the table", "404")
    return any(n in text for n in needles)


@dataclass
class MigrationStats:
    fetched: Dict[str, int] = field(default_factory=dict)
    inserted: Dict[str, int] = field(default_factory=dict)
    skipped_tables: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SupabaseToNeonMigrator:
    def __init__(self, supabase_url: str, supabase_key: str, neon_url: str, dry_run: bool = False):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.neon_url = neon_url
        self.dry_run = dry_run
        self.supabase: Any = None
        self.conn: Any = None
        self.stats = MigrationStats()

    def connect(self) -> None:
        from supabase import create_client

        self.supabase = create_client(self.supabase_url, self.supabase_key)
        logger.info("Connected to Supabase")

        if self.dry_run:
            self.conn = psycopg2.connect(self.neon_url)
            self.conn.autocommit = False
            logger.info("Connected to Neon (dry-run mode)")
            return

        from bot.utils.neon_db import init_neon, neon_db

        init_neon(self.neon_url)
        if neon_db is None or neon_db.conn is None:
            raise RuntimeError("Neon initialization failed")
        self.conn = neon_db.conn
        logger.info("Connected to Neon and ensured schema")

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass

    def fetch_all(self, table: str, page_size: int = 1000) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            try:
                response = self.supabase.table(table).select("*").range(offset, offset + page_size - 1).execute()
                batch = getattr(response, "data", None) or []
            except Exception as exc:
                if _missing_table_error(exc):
                    logger.info("Skipping missing table: %s", table)
                    self.stats.skipped_tables.append(table)
                    return []
                raise

            batch_rows = [row for row in batch if isinstance(row, dict)]
            rows.extend(batch_rows)
            if len(batch_rows) < page_size:
                break
            offset += page_size

        self.stats.fetched[table] = len(rows)
        return rows

    def _execute_values(
        self,
        table_name: str,
        sql: str,
        values: Sequence[Tuple[Any, ...]],
        page_size: int = 500,
    ) -> None:
        if not values:
            self.stats.inserted[table_name] = 0
            return

        if self.dry_run:
            self.stats.inserted[table_name] = len(values)
            logger.info("[dry-run] %s rows prepared for %s", len(values), table_name)
            return

        with self.conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, values, page_size=page_size)
        self.conn.commit()
        self.stats.inserted[table_name] = len(values)
        logger.info("Migrated %s rows into %s", len(values), table_name)

    def migrate_global_music_index(self) -> None:
        rows = self.fetch_all("global_music_index")
        values: List[Tuple[Any, ...]] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            sources = row.get("sources") if isinstance(row.get("sources"), list) else []
            first_source = sources[0] if sources and isinstance(sources[0], dict) else {}

            jamendo_track_id = _to_int(row.get("jamendo_track_id"))
            if jamendo_track_id is None:
                seed = "|".join(
                    [
                        str(row.get("query_key") or ""),
                        str(row.get("title") or ""),
                        str(row.get("artist") or ""),
                        str(row.get("audio_url") or ""),
                        str(metadata.get("url") or ""),
                        str(first_source.get("url") or ""),
                    ]
                )
                jamendo_track_id = _stable_int(seed)

            title = row.get("title") or metadata.get("title") or "Unknown"
            artist = row.get("artist") or metadata.get("artist") or "Unknown Artist"
            duration = _to_int(row.get("duration")) or 0
            thumbnail_url = row.get("thumbnail_url") or row.get("thumbnail") or metadata.get("thumbnail")
            audio_url = (
                row.get("audio_url")
                or row.get("stream_url")
                or metadata.get("stream_url")
                or metadata.get("url")
                or first_source.get("stream_url")
                or first_source.get("url")
                or ""
            )
            created_at = row.get("last_played")
            values.append((jamendo_track_id, title, artist, duration, thumbnail_url, audio_url, created_at))

        sql = """
            INSERT INTO music_index
            (jamendo_track_id, title, artist, duration, thumbnail_url, audio_url, created_at)
            VALUES %s
            ON CONFLICT (jamendo_track_id) DO UPDATE SET
                title = EXCLUDED.title,
                artist = EXCLUDED.artist,
                duration = EXCLUDED.duration,
                thumbnail_url = EXCLUDED.thumbnail_url,
                audio_url = EXCLUDED.audio_url,
                updated_at = CURRENT_TIMESTAMP
        """
        self._execute_values("music_index", sql, values)

    def migrate_groups(self) -> None:
        rows = self.fetch_all("groups")
        values = [
            (
                row.get("id"),
                row.get("title") or "",
                row.get("lang") or "en",
                bool(row.get("is_active", True)),
                row.get("joined_at"),
                _json_text(row.get("settings"), {}),
            )
            for row in rows
            if row.get("id") is not None
        ]
        sql = """
            INSERT INTO groups (id, title, lang, is_active, joined_at, settings)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                lang = EXCLUDED.lang,
                is_active = EXCLUDED.is_active,
                joined_at = EXCLUDED.joined_at,
                settings = EXCLUDED.settings::jsonb,
                updated_at = CURRENT_TIMESTAMP
        """
        self._execute_values("groups", sql, values)

    def migrate_sudo_users(self) -> None:
        rows = self.fetch_all("sudo_users")
        values = [
            (row.get("id"), row.get("name"), row.get("added_by"), row.get("added_at"))
            for row in rows
            if row.get("id") is not None
        ]
        sql = """
            INSERT INTO sudo_users (id, name, added_by, added_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                added_by = EXCLUDED.added_by,
                added_at = EXCLUDED.added_at
        """
        self._execute_values("sudo_users", sql, values)

    def migrate_gbanned(self) -> None:
        rows = self.fetch_all("gbanned")
        values = [
            (row.get("id"), row.get("reason"), row.get("banned_by"), row.get("banned_at"))
            for row in rows
            if row.get("id") is not None
        ]
        sql = """
            INSERT INTO gbanned (id, reason, banned_by, banned_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                reason = EXCLUDED.reason,
                banned_by = EXCLUDED.banned_by,
                banned_at = EXCLUDED.banned_at
        """
        self._execute_values("gbanned", sql, values)

    def migrate_group_bans(self) -> None:
        rows = self.fetch_all("group_bans")
        values = [
            (row.get("chat_id"), row.get("user_id"), row.get("banned_at"))
            for row in rows
            if row.get("chat_id") is not None and row.get("user_id") is not None
        ]
        sql = """
            INSERT INTO groupbans (chat_id, user_id, banned_at)
            VALUES %s
            ON CONFLICT (chat_id, user_id) DO UPDATE SET
                banned_at = EXCLUDED.banned_at
        """
        self._execute_values("groupbans", sql, values)

    def migrate_queues(self) -> None:
        rows = self.fetch_all("queues")
        values = [
            (
                row.get("chat_id"),
                _json_text(row.get("queue_data"), {}),
                row.get("created_at"),
            )
            for row in rows
            if row.get("chat_id") is not None
        ]
        sql = """
            INSERT INTO queues (chat_id, queue_data, created_at)
            VALUES %s
            ON CONFLICT (chat_id) DO UPDATE SET
                queue_data = EXCLUDED.queue_data::jsonb,
                updated_at = CURRENT_TIMESTAMP
        """
        self._execute_values("queues", sql, values)

    def migrate_chats(self) -> None:
        rows = self.fetch_all("chats")
        values = [
            (
                row.get("chat_id"),
                row.get("title"),
                row.get("username"),
                row.get("type"),
                bool(row.get("is_active", True)),
                row.get("created_at"),
            )
            for row in rows
            if row.get("chat_id") is not None
        ]
        sql = """
            INSERT INTO chats (chat_id, title, username, type, is_active, created_at)
            VALUES %s
            ON CONFLICT (chat_id) DO UPDATE SET
                title = EXCLUDED.title,
                username = EXCLUDED.username,
                type = EXCLUDED.type,
                is_active = EXCLUDED.is_active,
                updated_at = CURRENT_TIMESTAMP
        """
        self._execute_values("chats", sql, values)

    def migrate_play_history(self) -> None:
        rows = self.fetch_all("play_history")
        values: List[Tuple[Any, ...]] = []
        for row in rows:
            track_id = _to_int(row.get("jamendo_track_id"))
            if track_id is None:
                track_id = _to_int(row.get("track_id"))
            if track_id is None:
                seed = "|".join(
                    [
                        str(row.get("chat_id") or ""),
                        str(row.get("track_id") or ""),
                        str(row.get("title") or ""),
                        str(row.get("artist") or ""),
                        str(row.get("played_at") or ""),
                    ]
                )
                track_id = _stable_int(seed)

            if row.get("chat_id") is None:
                continue
            values.append((row.get("chat_id"), track_id, row.get("title"), row.get("artist"), row.get("played_at")))

        sql = """
            INSERT INTO play_history (chat_id, jamendo_track_id, title, artist, played_at)
            VALUES %s
        """
        self._execute_values("play_history", sql, values)

    def migrate_playlists(self) -> None:
        rows = self.fetch_all("playlists")
        values = [
            (
                row.get("id"),
                row.get("name"),
                row.get("creator_user_id"),
                row.get("jamendo_playlist_id"),
                bool(row.get("is_collaborative", False)),
                bool(row.get("is_public", False)),
                _json_text(row.get("jamendo_token"), None),
                row.get("created_at"),
            )
            for row in rows
            if row.get("id") is not None
        ]
        sql = """
            INSERT INTO playlists
            (id, name, creator_user_id, jamendo_playlist_id, is_collaborative, is_public, jamendo_token, created_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                creator_user_id = EXCLUDED.creator_user_id,
                jamendo_playlist_id = EXCLUDED.jamendo_playlist_id,
                is_collaborative = EXCLUDED.is_collaborative,
                is_public = EXCLUDED.is_public,
                jamendo_token = EXCLUDED.jamendo_token::jsonb
        """
        self._execute_values("playlists", sql, values)

    def migrate_playlist_tracks(self) -> None:
        rows = self.fetch_all("playlist_tracks")
        values = [
            (
                row.get("id"),
                row.get("playlist_id"),
                row.get("jamendo_track_id"),
                row.get("position"),
                row.get("added_by"),
                row.get("added_at"),
            )
            for row in rows
            if row.get("id") is not None and row.get("playlist_id") is not None
        ]
        sql = """
            INSERT INTO playlist_tracks (id, playlist_id, jamendo_track_id, position, added_by, added_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                playlist_id = EXCLUDED.playlist_id,
                jamendo_track_id = EXCLUDED.jamendo_track_id,
                position = EXCLUDED.position,
                added_by = EXCLUDED.added_by,
                added_at = EXCLUDED.added_at
        """
        self._execute_values("playlist_tracks", sql, values)

    def migrate_radio_shows(self) -> None:
        rows = self.fetch_all("radio_shows")
        values = [
            (
                row.get("id"),
                row.get("chat_id"),
                row.get("host_user_id"),
                row.get("show_name"),
                row.get("description"),
                row.get("schedule_day_of_week"),
                row.get("schedule_time"),
                row.get("genre_tags"),
                row.get("duration_minutes"),
                bool(row.get("is_active", True)),
                row.get("created_at"),
            )
            for row in rows
            if row.get("id") is not None
        ]
        sql = """
            INSERT INTO radio_shows
            (id, chat_id, host_user_id, show_name, description, schedule_day_of_week, schedule_time, genre_tags, duration_minutes, is_active, created_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                chat_id = EXCLUDED.chat_id,
                host_user_id = EXCLUDED.host_user_id,
                show_name = EXCLUDED.show_name,
                description = EXCLUDED.description,
                schedule_day_of_week = EXCLUDED.schedule_day_of_week,
                schedule_time = EXCLUDED.schedule_time,
                genre_tags = EXCLUDED.genre_tags,
                duration_minutes = EXCLUDED.duration_minutes,
                is_active = EXCLUDED.is_active
        """
        self._execute_values("radio_shows", sql, values)

    def migrate_show_tracks(self) -> None:
        rows = self.fetch_all("show_tracks")
        values = [
            (
                row.get("id"),
                row.get("show_id"),
                _to_int(row.get("jamendo_track_id")) or _stable_int(str(row.get("jamendo_track_id") or "")),
                row.get("position"),
                row.get("added_by"),
                row.get("added_at"),
            )
            for row in rows
            if row.get("id") is not None and row.get("show_id") is not None
        ]
        sql = """
            INSERT INTO show_tracks (id, show_id, jamendo_track_id, position, added_by, added_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                show_id = EXCLUDED.show_id,
                jamendo_track_id = EXCLUDED.jamendo_track_id,
                position = EXCLUDED.position,
                added_by = EXCLUDED.added_by,
                added_at = EXCLUDED.added_at
        """
        self._execute_values("show_tracks", sql, values)

    def migrate_anon_requests(self) -> None:
        rows = self.fetch_all("anon_requests")
        values = [
            (row.get("id"), row.get("track_id"), row.get("requested_by"), row.get("chat_id"), row.get("created_at"))
            for row in rows
            if row.get("id") is not None
        ]
        sql = """
            INSERT INTO anon_requests (id, track_id, requested_by, chat_id, created_at)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                track_id = EXCLUDED.track_id,
                requested_by = EXCLUDED.requested_by,
                chat_id = EXCLUDED.chat_id,
                created_at = EXCLUDED.created_at
        """
        self._execute_values("anon_requests", sql, values)

    def migrate_vote_sessions(self) -> None:
        rows = self.fetch_all("vote_sessions")
        values = [
            (
                row.get("message_id"),
                row.get("track_id"),
                row.get("chat_id"),
                _to_int(row.get("yes_votes")) or 0,
                _to_int(row.get("no_votes")) or 0,
                bool(row.get("expired", False)),
                row.get("created_at"),
            )
            for row in rows
            if row.get("message_id") is not None
        ]
        sql = """
            INSERT INTO vote_sessions (message_id, track_id, chat_id, yes_votes, no_votes, expired, created_at)
            VALUES %s
            ON CONFLICT (message_id) DO UPDATE SET
                track_id = EXCLUDED.track_id,
                chat_id = EXCLUDED.chat_id,
                yes_votes = EXCLUDED.yes_votes,
                no_votes = EXCLUDED.no_votes,
                expired = EXCLUDED.expired,
                created_at = EXCLUDED.created_at
        """
        self._execute_values("vote_sessions", sql, values)

    def _set_serial_sequences(self) -> None:
        if self.dry_run:
            return
        table_id_pairs = [
            ("playlists", "id"),
            ("playlist_tracks", "id"),
            ("radio_shows", "id"),
            ("show_tracks", "id"),
            ("anon_requests", "id"),
            ("chats", "id"),
            ("queues", "id"),
            ("play_history", "id"),
            ("music_index", "id"),
        ]
        with self.conn.cursor() as cur:
            for table, column in table_id_pairs:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, %s), COALESCE(MAX({column}), 1), true) FROM {table}",
                    (table, column),
                )
        self.conn.commit()

    def run(self) -> None:
        self.connect()
        steps: List[Tuple[str, Callable[[], None]]] = [
            ("global_music_index -> music_index", self.migrate_global_music_index),
            ("groups", self.migrate_groups),
            ("sudo_users", self.migrate_sudo_users),
            ("gbanned", self.migrate_gbanned),
            ("group_bans -> groupbans", self.migrate_group_bans),
            ("queues", self.migrate_queues),
            ("chats", self.migrate_chats),
            ("play_history", self.migrate_play_history),
            ("playlists", self.migrate_playlists),
            ("playlist_tracks", self.migrate_playlist_tracks),
            ("radio_shows", self.migrate_radio_shows),
            ("show_tracks", self.migrate_show_tracks),
            ("anon_requests", self.migrate_anon_requests),
            ("vote_sessions", self.migrate_vote_sessions),
        ]
        for label, step in steps:
            try:
                logger.info("Migrating: %s", label)
                step()
            except Exception as exc:
                if self.conn is not None and not self.dry_run:
                    try:
                        self.conn.rollback()
                    except Exception:
                        pass
                msg = f"{label}: {exc}"
                self.stats.errors.append(msg)
                logger.error("Migration step failed: %s", msg)

        if self.stats.errors:
            logger.warning("Migration completed with %s error(s)", len(self.stats.errors))
        else:
            self._set_serial_sequences()
            logger.info("Migration completed successfully")

        logger.info("Fetched rows by table: %s", self.stats.fetched)
        logger.info("Inserted rows by table: %s", self.stats.inserted)
        if self.stats.skipped_tables:
            logger.info("Skipped missing tables: %s", ", ".join(self.stats.skipped_tables))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate data from Supabase to Neon")
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--supabase-key", default=os.getenv("SUPABASE_KEY"))
    parser.add_argument("--neon-url", default=os.getenv("NEON_DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="Read and transform without writing to Neon")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.supabase_url or not args.supabase_key:
        logger.error("SUPABASE_URL and SUPABASE_KEY are required for migration source.")
        sys.exit(1)
    if not args.neon_url:
        logger.error("NEON_DATABASE_URL is required for migration target.")
        sys.exit(1)

    migrator = SupabaseToNeonMigrator(
        supabase_url=args.supabase_url,
        supabase_key=args.supabase_key,
        neon_url=args.neon_url,
        dry_run=args.dry_run,
    )
    try:
        migrator.run()
    finally:
        migrator.close()

    if migrator.stats.errors:
        sys.exit(2)


if __name__ == "__main__":
    main()

