"""Supabase PostgreSQL database support for migration from MongoDB."""

import os
import json
import logging
import random
import urllib.request
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import supabase
try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    logger.warning("supabase package not installed. Run: pip install supabase")


class SupabaseDatabase:
    """Supabase PostgreSQL database wrapper for bot data."""
    
    def __init__(self, url: str, key: str):
        if not HAS_SUPABASE:
            raise ImportError("supabase package required. Install with: pip install supabase")
        
        self.url = url
        self.key = key
        self.client: Client = create_client(url, key)
        self._supports_stream_url_column: Optional[bool] = None
        self._warned_stream_url_fallback = False
        self._init_tables()
        self._init_storage()
    
    def _init_storage(self):
        """Initialize bot-assets bucket and ensure startup assets exist."""
        try:
            # Check if bucket exists
            buckets = self.client.storage.list_buckets()
            bucket_exists = any(b.name == "bot-assets" for b in buckets)
            
            if not bucket_exists:
                # Create a public bucket using the service role key
                self.client.storage.create_bucket("bot-assets", {"public": True})
                logger.info("Created Supabase storage bucket 'bot-assets'")
                
            # Pre-upload Brook welcome image if missing
            files = self.client.storage.from_("bot-assets").list()
            brook_exists = any(f.get("name") == "brook_start.png" for f in files)
            
            if not brook_exists:
                local_path = "assets/brook_start.png"
                if os.path.exists(local_path):
                    try:
                        with open(local_path, "rb") as f:
                            img_data = f.read()
                            
                        self.client.storage.from_("bot-assets").upload("brook_start.png", img_data, {"content-type": "image/png"})
                        logger.info("Successfully uploaded Brook start image to Supabase storage")
                    except Exception as e:
                        logger.warning(f"Failed to upload local Brook image to Supabase: {e}")
                else:
                    logger.warning(f"Local asset {local_path} not found to upload.")
                    
        except Exception as e:
            logger.error(f"Error initializing Supabase storage: {e}")

    def get_start_image(self) -> str:
        """Get the public URL for the Brook start image from Supabase."""
        try:
            url = self.client.storage.from_("bot-assets").get_public_url("brook_start.png")
            return url
        except Exception:
            return "https://github.com/edent/SuperTinyIcons/raw/master/images/svg/telegram.svg" # A tiny fallback

            
    def _init_tables(self):
        """Initialize database tables if they don't exist.

        NOTE: The canonical schema and migrations are managed in
        `supabase_setup.sql` in the repository. Do NOT rely on an inline
        multi-line SQL schema here. In particular, the `global_music_index`
        table is defined in `supabase_setup.sql` and uses explicit `::jsonb`
        casts for JSONB defaults (single-line JSON literals) to avoid SQL
        parser issues in the Supabase SQL editor.

        Ensure that `global_music_index` exists with the expected columns;
        for example (reference only):

                    - query_key TEXT PRIMARY KEY
                    - title TEXT
                    - artist TEXT
                    - metadata JSONB NOT NULL
          - sources JSONB DEFAULT '[]'::jsonb
                    - last_played TIMESTAMP DEFAULT NOW()

        This method does not execute DDL; run `supabase_setup.sql` in the
        Supabase SQL editor or via migrations to apply the schema.
        """
        # The repository script `supabase_setup.sql` is the source of truth
        # for schema creation and includes the `global_music_index` table.
        logger.info(
            "Supabase schema is managed via supabase_setup.sql; ensure `global_music_index` exists."
        )

    @staticmethod
    def _global_music_index_select_fields(include_audio_url: bool) -> str:
        base_fields = "query_key,jamendo_track_id,title,artist,duration,thumbnail_url,metadata,sources,last_played"
        if include_audio_url:
            return base_fields + ",audio_url"
        return base_fields

    @staticmethod
    def _is_missing_stream_url_column_error(exc: Exception) -> bool:
        err_str = str(exc)
        err_lower = err_str.lower()
        return (
            "stream_url" in err_lower
            and (
                "42703" in err_str
                or "pgrst204" in err_lower
                or "schema cache" in err_lower
                or "does not exist" in err_lower
            )
        )

    def _disable_stream_url_column(self, reason: str) -> None:
        self._supports_stream_url_column = False
        if not self._warned_stream_url_fallback:
            logger.warning(reason)
            self._warned_stream_url_fallback = True
    
    # Group management
    async def get_group(self, chat_id: int) -> dict:
        """Get group settings or create default."""
        try:
            result = self.client.table("groups").select("*").eq("id", chat_id).execute()
            
            if result.data and len(result.data) > 0:
                row = result.data[0]
                return {
                    "_id": row["id"],
                    "title": row.get("title", ""),
                    "lang": row.get("lang", "en"),
                    "is_active": row.get("is_active", True),
                    "settings": row.get("settings", {}),
                    "joined_at": row.get("joined_at", datetime.utcnow())
                }
            
            # Create default group
            default_settings = {
                "play_on_join": True,
                "max_queue": 100,
                "vol_default": 100,
                "loop_mode": "none",
                "quality": "high",
                "thumb_mode": True,
            }
            
            new_group = {
                "id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": default_settings,
                "joined_at": datetime.utcnow().isoformat()
            }
            
            self.client.table("groups").insert(new_group).execute()
            
            return {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": default_settings
            }
            
        except Exception as e:
            logger.error(f"Error getting group from Supabase: {e}")
            # Return default on error
            return {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": {
                    "play_on_join": True,
                    "max_queue": 100,
                    "vol_default": 100,
                    "loop_mode": "none",
                    "quality": "high",
                    "thumb_mode": True,
                }
            }
    
    async def update_group(self, chat_id: int, updates: dict):
        """Update group settings."""
        try:
            # Get current data first
            result = self.client.table("groups").select("*").eq("id", chat_id).execute()
            
            if not result.data:
                # Create if doesn't exist
                await self.get_group(chat_id)
                result = self.client.table("groups").select("*").eq("id", chat_id).execute()
            
            current = result.data[0]
            
            # Build update data
            update_data = {}
            current_settings = current.get("settings", {}) or {}

            def _merge_dotted_settings(settings_dict, dotted_key, value):
                parts = dotted_key.split(".")[1:]
                target = settings_dict
                for part in parts[:-1]:
                    if part not in target or not isinstance(target[part], dict):
                        target[part] = {}
                    target = target[part]
                target[parts[-1]] = value

            if "settings" in updates and isinstance(updates["settings"], dict):
                current_settings.update(updates["settings"])

            for key, value in updates.items():
                if key.startswith("settings."):
                    _merge_dotted_settings(current_settings, key, value)

            if current_settings != current.get("settings", {}):
                update_data["settings"] = current_settings
            
            if "title" in updates:
                update_data["title"] = updates["title"]
            
            if "is_active" in updates:
                update_data["is_active"] = updates["is_active"]
            
            if "lang" in updates:
                update_data["lang"] = updates["lang"]
            
            if update_data:
                self.client.table("groups").update(update_data).eq("id", chat_id).execute()
                
        except Exception as e:
            logger.error(f"Error updating group in Supabase: {e}")
    
    async def set_group_active(self, chat_id: int, active: bool):
        """Set group active status."""
        try:
            self.client.table("groups").update({"is_active": active}).eq("id", chat_id).execute()
        except Exception as e:
            logger.error(f"Error setting group active: {e}")
    
    # Sudo users
    async def add_sudo(self, user_id: int, name: str, added_by: int):
        """Add a sudo user."""
        try:
            data = {
                "id": user_id,
                "name": name,
                "added_by": added_by,
                "added_at": datetime.utcnow().isoformat()
            }
            self.client.table("sudo_users").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error adding sudo: {e}")
    
    async def remove_sudo(self, user_id: int):
        """Remove a sudo user."""
        try:
            self.client.table("sudo_users").delete().eq("id", user_id).execute()
        except Exception as e:
            logger.error(f"Error removing sudo: {e}")
    
    async def get_sudo_users(self) -> list:
        """Get all sudo users."""
        try:
            result = self.client.table("sudo_users").select("*").execute()
            if result.data:
                return [{"_id": r["id"], "name": r.get("name"), "added_by": r.get("added_by")} for r in result.data]
            return []
        except Exception as e:
            logger.error(f"Error getting sudo users: {e}")
            return []
    
    async def is_sudo(self, user_id: int) -> bool:
        """Check if user is sudo."""
        try:
            result = self.client.table("sudo_users").select("*").eq("id", user_id).execute()
            return len(result.data) > 0
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                # Table missing - only log once or keep it concise
                logger.warning("Supabase table 'sudo_users' missing. Create it via SQL: CREATE TABLE sudo_users (id BIGINT PRIMARY KEY, name TEXT);")
            else:
                logger.debug(f"Sudo check error: {e}")
            return False
    
    # Global bans
    async def gban_user(self, user_id: int, reason: str, banned_by: int):
        """Globally ban a user."""
        try:
            data = {
                "id": user_id,
                "reason": reason,
                "banned_by": banned_by,
                "banned_at": datetime.utcnow().isoformat()
            }
            self.client.table("gbanned").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error gbanning user: {e}")
    
    async def ungban_user(self, user_id: int):
        """Remove global ban."""
        try:
            self.client.table("gbanned").delete().eq("id", user_id).execute()
        except Exception as e:
            logger.error(f"Error ungbanning: {e}")
    
    async def is_gbanned(self, user_id: int) -> bool:
        """Check if user is globally banned."""
        try:
            result = self.client.table("gbanned").select("*").eq("id", user_id).execute()
            return len(result.data) > 0
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                logger.warning("Supabase table 'gbanned' missing. Create it via SQL: CREATE TABLE gbanned (id BIGINT PRIMARY KEY, reason TEXT);")
            else:
                logger.debug(f"Gban check error: {e}")
            return False
    
    # Group bans
    async def ban_user(self, chat_id: int, user_id: int):
        """Ban user in a specific group."""
        try:
            data = {
                "chat_id": chat_id,
                "user_id": user_id,
                "banned_at": datetime.utcnow().isoformat()
            }
            self.client.table("group_bans").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error banning user: {e}")
    
    async def unban_user(self, chat_id: int, user_id: int):
        """Unban user in a specific group."""
        try:
            self.client.table("group_bans").delete().eq("chat_id", chat_id).eq("user_id", user_id).execute()
        except Exception as e:
            logger.error(f"Error unbanning: {e}")
    
    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        """Check if user is banned in a group."""
        try:
            result = self.client.table("group_bans").select("*").eq("chat_id", chat_id).eq("user_id", user_id).execute()
            return len(result.data) > 0
        except Exception as e:
            logger.error(f"Error checking ban: {e}")
            return False
    
    # Stats
    async def get_stats(self) -> dict:
        """Get bot statistics."""
        try:
            groups_result = self.client.table("groups").select("*").execute()
            active_result = self.client.table("groups").select("*").eq("is_active", True).execute()
            sudo_result = self.client.table("sudo_users").select("*").execute()
            gban_result = self.client.table("gbanned").select("*").execute()
            
            return {
                "total_groups": len(groups_result.data) if groups_result.data else 0,
                "active_groups": len(active_result.data) if active_result.data else 0,
                "sudo_users": len(sudo_result.data) if sudo_result.data else 0,
                "gbanned_users": len(gban_result.data) if gban_result.data else 0,
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "total_groups": 0,
                "active_groups": 0,
                "sudo_users": 0,
                "gbanned_users": 0,
            }

    async def search_global_music_index(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search cached global catalog first to reduce external API calls."""
        q = (query or "").strip()
        if not q:
            return []

        rows: List[Dict[str, Any]] = []

        # Prefer RPC search backed by pg_trgm/similarity ordering.
        try:
            rpc_result = self.client.rpc("search_music_index", {"p_query": q, "p_limit": max(1, limit)}).execute()
            rpc_data = getattr(rpc_result, "data", None)
            if isinstance(rpc_data, list):
                rows = [r for r in rpc_data if isinstance(r, dict)]
        except Exception as e:
            logger.debug(f"search_music_index RPC unavailable, using fallback query: {e}")

        # Fallback path if RPC isn't deployed yet.
        if not rows:
            include_audio_url = self._supports_stream_url_column is not False
            try:
                like_query = f"%{q}%"
                result = (
                    self.client.table("global_music_index")
                    .select(self._global_music_index_select_fields(include_audio_url))
                    .or_(f"title.ilike.{like_query},artist.ilike.{like_query}")
                    .order("last_played", desc=True)
                    .limit(max(1, limit))
                    .execute()
                )
                rows = [r for r in (getattr(result, "data", None) or []) if isinstance(r, dict)]
            except Exception as e:
                if include_audio_url and self._is_missing_stream_url_column_error(e):
                    self._disable_stream_url_column(
                        "Supabase global_music_index.stream_url is unavailable in the live schema; falling back to legacy index fields until migration is applied."
                    )
                    try:
                        like_query = f"%{q}%"
                        result = (
                            self.client.table("global_music_index")
                            .select(self._global_music_index_select_fields(False))
                            .or_(f"title.ilike.{like_query},artist.ilike.{like_query}")
                            .order("last_played", desc=True)
                            .limit(max(1, limit))
                            .execute()
                        )
                        rows = [r for r in (getattr(result, "data", None) or []) if isinstance(r, dict)]
                    except Exception as retry_exc:
                        err_str = str(retry_exc)
                        if "PGRST205" in err_str:
                            logger.warning("Supabase table 'global_music_index' is missing. Action required: Run the contents of 'supabase_setup.sql' in your Supabase SQL Editor.")
                        else:
                            logger.error(f"Failed to search global_music_index: {retry_exc}")
                        return []
                else:
                    err_str = str(e)
                    if "PGRST205" in err_str:
                        logger.warning("Supabase table 'global_music_index' is missing. Action required: Run the contents of 'supabase_setup.sql' in your Supabase SQL Editor.")
                    else:
                        logger.error(f"Failed to search global_music_index: {e}")
                return []

        tracks: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            sources = row.get("sources") if isinstance(row.get("sources"), list) else []

            title = row.get("title") or metadata.get("title") or q
            artist = row.get("artist") or metadata.get("artist") or metadata.get("uploader") or "Unknown Artist"
            duration_raw = row.get("duration") if row.get("duration") is not None else metadata.get("duration", 0)
            try:
                duration = int(duration_raw or 0)
            except Exception:
                duration = 0

            jamendo_track_id = row.get("jamendo_track_id") or metadata.get("id") or metadata.get("jamendo_track_id")
            thumb = row.get("thumbnail") or metadata.get("thumbnail") or metadata.get("thumb")

            stream_url = row.get("stream_url") or metadata.get("stream_url") or metadata.get("url") or ""
            if not stream_url:
                for src in sources:
                    if isinstance(src, dict):
                        stream_url = src.get("stream_url") or src.get("url") or ""
                        if stream_url:
                            break

            tracks.append({
                "title": title,
                "artist": artist,
                "uploader": artist,
                "duration": duration,
                "url": stream_url,
                "stream_url": stream_url,
                "thumbnail": thumb,
                "source": "global_index",
                "origin_source": row.get("source") or metadata.get("source") or "unknown",
                "id": jamendo_track_id,
                "jamendo_track_id": jamendo_track_id,
                "metadata": metadata,
                "sources": sources,
                "query_key": row.get("query_key"),
            })

        return tracks[: max(1, limit)]

    async def save_track_to_index(self, query: str, track: dict):
        """🟢 Saves a track to Supabase, but automatically deletes old ones to protect the Free Tier."""
        try:
            query_key = query.strip().lower()
            jamendo_track_id = track.get("id") or track.get("jamendo_track_id")
            source_name = track.get("source", "unknown")
            stream_url = track.get("url") or track.get("stream_url") or ""
            saved_at = datetime.utcnow().isoformat()

            include_audio_url = self._supports_stream_url_column is not False

            metadata = {
                "title": track.get("title", "Unknown"),
                "artist": track.get("artist") or track.get("uploader") or "Unknown Artist",
                "duration": track.get("duration", 0),
                "thumbnail": track.get("thumbnail") or track.get("thumb") or "",
                "source": source_name,
                "id": jamendo_track_id,
                "url": stream_url,
                "stream_url": stream_url,
                "saved_at": saved_at,
            }

            if isinstance(track.get("metadata"), dict):
                # Keep any provider-specific metadata while preserving canonical keys.
                metadata = {**track.get("metadata"), **metadata}

            sources_payload: List[Dict[str, Any]] = []
            if isinstance(track.get("sources"), list):
                sources_payload.extend([s for s in track.get("sources") if isinstance(s, dict)])

            sources_payload.append({
                "source": source_name,
                "jamendo_track_id": jamendo_track_id,
                "url": stream_url,
                "stream_url": stream_url,
                "saved_at": saved_at,
            })

            data = {
                "query_key": query_key,
                "jamendo_track_id": jamendo_track_id,
                "title": metadata.get("title", "Unknown"),
                "artist": metadata.get("artist", "Unknown Artist"),
                "duration": track.get("duration", 0),
                "thumbnail": metadata.get("thumbnail", ""),
                "source": source_name,
                "metadata": metadata,
                "sources": sources_payload,
                "last_played": saved_at,
            }

            if include_audio_url:
                data["stream_url"] = stream_url

            # 1. Save or update the current track
            try:
                self.client.table("global_music_index").upsert(data).execute()
                if include_audio_url:
                    self._supports_stream_url_column = True
            except Exception as upsert_exc:
                if include_audio_url and self._is_missing_stream_url_column_error(upsert_exc):
                    self._disable_stream_url_column(
                        "Supabase global_music_index.stream_url is unavailable in the live schema; storing the resolved URL only in metadata/sources until migration is applied."
                    )
                    fallback_data = dict(data)
                    fallback_data.pop("stream_url", None)
                    self.client.table("global_music_index").upsert(fallback_data).execute()
                else:
                    raise

            # 2. Free Tier Protection: Randomly check the database size (10% chance)
            if random.random() < 0.10:
                try:
                    # Use a head/select count without fetching rows when possible.
                    count_result = self.client.table("global_music_index").select("query_key", count="exact", head=True).execute()
                    total_songs = getattr(count_result, "count", 0) or 0
                except Exception as count_exception:
                    logger.debug(f"Supabase index size check failed: {count_exception}")
                    total_songs = 0

                MAX_SONGS = 50000
                if total_songs > MAX_SONGS:
                    # Attempt to acquire a Postgres advisory lock to serialize pruning
                    # across multiple instances. Supabase RPC can only invoke SQL
                    # functions, so we call wrapper RPCs (try_lock/try_unlock)
                    # defined in supabase_setup.sql.
                    LOCK_KEY = 987654321  # arbitrary stable lock id for pruning
                    locked = False

                    def _rpc_bool(response: Any) -> bool:
                        """Best-effort bool extraction from Supabase RPC responses."""
                        data = getattr(response, "data", None)
                        if isinstance(data, bool):
                            return data
                        if isinstance(data, dict):
                            for value in data.values():
                                if isinstance(value, bool):
                                    return value
                            return False
                        if isinstance(data, list) and data:
                            first = data[0]
                            if isinstance(first, bool):
                                return first
                            if isinstance(first, dict):
                                for value in first.values():
                                    if isinstance(value, bool):
                                        return value
                        return False

                    try:
                        # Try different client APIs depending on supabase-py version
                        if hasattr(self.client, "rpc"):
                            try:
                                res = self.client.rpc("try_lock", {"p_key": LOCK_KEY}).execute()
                                locked = _rpc_bool(res)
                            except Exception:
                                locked = False

                        if not locked and hasattr(self.client, "postgrest") and hasattr(self.client.postgrest, "rpc"):
                            try:
                                res = self.client.postgrest.rpc("try_lock", {"p_key": LOCK_KEY}).execute()
                                locked = _rpc_bool(res)
                            except Exception:
                                locked = False
                    except Exception:
                        locked = False

                    try:
                        if locked:
                            # Inside the lock: re-check count to avoid over-deletion
                            # Re-check count inside advisory lock using head=True
                            count_result = self.client.table("global_music_index").select("query_key", count="exact", head=True).execute()
                            total_songs_locked = getattr(count_result, "count", 0) or 0

                            if total_songs_locked > MAX_SONGS:
                                oldest = self.client.table("global_music_index") \
                                    .select("query_key") \
                                    .order("last_played", desc=False) \
                                    .limit(1000) \
                                    .execute()

                                if getattr(oldest, "data", None):
                                    old_keys = [item["query_key"] for item in oldest.data if item.get("query_key")]
                                    if old_keys:
                                        self.client.table("global_music_index").delete().in_("query_key", old_keys).execute()
                                        logger.info("🧹 Free Tier Protection: Deleted 1,000 old songs from Supabase index.")
                        else:
                            # Could not acquire lock; perform a conservative re-check
                            count_result2 = self.client.table("global_music_index").select("query_key", count="exact", head=True).execute()
                            total_songs_2 = getattr(count_result2, "count", 0) or 0
                            if total_songs_2 > MAX_SONGS:
                                # Try to delete a small batch to reduce pressure without risking over-deletion
                                oldest = self.client.table("global_music_index") \
                                    .select("query_key") \
                                    .order("last_played", desc=False) \
                                    .limit(200) \
                                    .execute()
                                if getattr(oldest, "data", None):
                                    old_keys = [item["query_key"] for item in oldest.data if item.get("query_key")]
                                    if old_keys:
                                        self.client.table("global_music_index").delete().in_("query_key", old_keys).execute()
                                        logger.info("🧹 Free Tier Protection: Deleted a small batch of old songs from Supabase index (no advisory lock).")
                    finally:
                        # Release advisory lock if we acquired it
                        if locked:
                            try:
                                if hasattr(self.client, "rpc"):
                                    try:
                                        self.client.rpc("try_unlock", {"p_key": LOCK_KEY}).execute()
                                    except Exception:
                                        pass
                                elif hasattr(self.client, "postgrest") and hasattr(self.client.postgrest, "rpc"):
                                    try:
                                        self.client.postgrest.rpc("try_unlock", {"p_key": LOCK_KEY}).execute()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
        except Exception as e:
            logger.error(f"Failed to index track in Supabase: {e}")

    async def prune_inactive_data(self) -> int:
        """🟢 Deletes kicked/inactive groups to free up Supabase database space."""
        try:
            result = self.client.table("groups").delete().eq("is_active", False).execute()
            deleted_count = len(result.data) if getattr(result, "data", None) else 0
            logger.info(f"🧹 Auto-Prune: Freed space by deleting {deleted_count} inactive groups from Supabase.")
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to prune Supabase database: {e}")
            return 0

    async def get_all_groups(self) -> list:
        """Return all active groups as list of dicts with '_id' key."""
        try:
            result = self.client.table("groups").select("id").eq("is_active", True).execute()
            return [{"_id": row["id"]} for row in (result.data or [])]
        except Exception as e:
            logger.error(f"Error getting all groups: {e}")
            return []

    # Mini app sessions
    async def get_mini_app_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            result = (
                self.client.table("mini_app_sessions")
                .select("user_id,recent_tracks,preferences,last_chat_id,updated_at,created_at")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return {
                    "user_id": row.get("user_id"),
                    "recent_tracks": row.get("recent_tracks") if isinstance(row.get("recent_tracks"), list) else [],
                    "preferences": row.get("preferences") if isinstance(row.get("preferences"), dict) else {},
                    "last_chat_id": row.get("last_chat_id"),
                    "updated_at": row.get("updated_at"),
                    "created_at": row.get("created_at"),
                }
            return None
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                logger.warning(
                    "Supabase table 'mini_app_sessions' missing. Run docs/mini_app/02_DATABASE_SCHEMA.sql."
                )
            else:
                logger.error(f"Error getting mini app session: {e}")
            return None

    async def upsert_mini_app_session(
        self,
        user_id: int,
        recent_tracks: Optional[List[Dict[str, Any]]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        last_chat_id: Optional[int] = None,
    ) -> None:
        try:
            existing = await self.get_mini_app_session(user_id) or {}
            data = {
                "user_id": user_id,
                "recent_tracks": recent_tracks if recent_tracks is not None else existing.get("recent_tracks", []),
                "preferences": preferences if preferences is not None else existing.get("preferences", {}),
                "last_chat_id": last_chat_id if last_chat_id is not None else existing.get("last_chat_id"),
                "updated_at": datetime.utcnow().isoformat(),
            }
            self.client.table("mini_app_sessions").upsert(data).execute()
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                logger.warning(
                    "Supabase table 'mini_app_sessions' missing. Run docs/mini_app/02_DATABASE_SCHEMA.sql."
                )
            else:
                logger.error(f"Error upserting mini app session: {e}")

    # Lobby snapshots
    async def get_lobby_snapshot(self, chat_id: int) -> Optional[Dict[str, Any]]:
        try:
            result = (
                self.client.table("lobby_snapshots")
                .select("chat_id,now_playing,queue,status,position_seconds,participants,version,updated_at,created_at")
                .eq("chat_id", chat_id)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return {
                    "chat_id": row.get("chat_id"),
                    "now_playing": row.get("now_playing") if isinstance(row.get("now_playing"), dict) else None,
                    "queue": row.get("queue") if isinstance(row.get("queue"), list) else [],
                    "status": row.get("status") or "idle",
                    "position_seconds": int(row.get("position_seconds") or 0),
                    "participants": row.get("participants") if isinstance(row.get("participants"), list) else [],
                    "version": int(row.get("version") or 1),
                    "updated_at": row.get("updated_at"),
                    "created_at": row.get("created_at"),
                }
            return None
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                logger.warning(
                    "Supabase table 'lobby_snapshots' missing. Run docs/mini_app/02_DATABASE_SCHEMA.sql."
                )
            else:
                logger.error(f"Error getting lobby snapshot: {e}")
            return None

    async def upsert_lobby_snapshot(self, chat_id: int, snapshot: Dict[str, Any]) -> None:
        try:
            data = {
                "chat_id": chat_id,
                "now_playing": snapshot.get("now_playing"),
                "queue": snapshot.get("queue") if isinstance(snapshot.get("queue"), list) else [],
                "status": snapshot.get("status") or "idle",
                "position_seconds": int(snapshot.get("position_seconds") or 0),
                "participants": snapshot.get("participants") if isinstance(snapshot.get("participants"), list) else [],
                "version": int(snapshot.get("version") or 1),
                "updated_at": datetime.utcnow().isoformat(),
            }
            self.client.table("lobby_snapshots").upsert(data).execute()
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                logger.warning(
                    "Supabase table 'lobby_snapshots' missing. Run docs/mini_app/02_DATABASE_SCHEMA.sql."
                )
            else:
                logger.error(f"Error upserting lobby snapshot: {e}")

    # Migration helper
    async def migrate_from_mongodb(self, mongo_db):
        """Migrate data from MongoDB to Supabase."""
        logger.info("Starting migration from MongoDB to Supabase...")
        
        try:
            # Migrate groups
            groups = await mongo_db.db.groups.find().to_list(length=None)
            if groups:
                supabase_groups = []
                for g in groups:
                    supabase_groups.append({
                        "id": g["_id"],
                        "title": g.get("title", ""),
                        "lang": g.get("lang", "en"),
                        "is_active": g.get("is_active", True),
                        "settings": g.get("settings", {}),
                        "joined_at": g.get("joined_at", datetime.utcnow()).isoformat() if isinstance(g.get("joined_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                # Insert in batches
                for i in range(0, len(supabase_groups), 100):
                    batch = supabase_groups[i:i+100]
                    self.client.table("groups").upsert(batch).execute()
                
                logger.info(f"Migrated {len(groups)} groups")
            
            # Migrate sudo users
            sudos = await mongo_db.db.sudousers.find().to_list(length=None)
            if sudos:
                supabase_sudos = []
                for s in sudos:
                    supabase_sudos.append({
                        "id": s["_id"],
                        "name": s.get("name", ""),
                        "added_by": s.get("added_by"),
                        "added_at": s.get("added_at", datetime.utcnow()).isoformat() if isinstance(s.get("added_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                for i in range(0, len(supabase_sudos), 100):
                    batch = supabase_sudos[i:i+100]
                    self.client.table("sudo_users").upsert(batch).execute()
                
                logger.info(f"Migrated {len(sudos)} sudo users")
            
            # Migrate gbanned
            gbanned = await mongo_db.db.gbanned.find().to_list(length=None)
            if gbanned:
                supabase_gbanned = []
                for g in gbanned:
                    supabase_gbanned.append({
                        "id": g["_id"],
                        "reason": g.get("reason", ""),
                        "banned_by": g.get("banned_by"),
                        "banned_at": g.get("banned_at", datetime.utcnow()).isoformat() if isinstance(g.get("banned_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                for i in range(0, len(supabase_gbanned), 100):
                    batch = supabase_gbanned[i:i+100]
                    self.client.table("gbanned").upsert(batch).execute()
                
                logger.info(f"Migrated {len(gbanned)} gbanned users")
            
            # Migrate group bans
            bans = await mongo_db.db.groupbans.find().to_list(length=None)
            if bans:
                supabase_bans = []
                for b in bans:
                    supabase_bans.append({
                        "chat_id": b.get("chat_id"),
                        "user_id": b.get("user_id"),
                        "banned_at": b.get("banned_at", datetime.utcnow()).isoformat() if isinstance(b.get("banned_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                for i in range(0, len(supabase_bans), 100):
                    batch = supabase_bans[i:i+100]
                    self.client.table("group_bans").upsert(batch).execute()
                
                logger.info(f"Migrated {len(bans)} group bans")
            
            logger.info("Migration completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False

    async def create_playlist(self, name: str, user_id: int) -> int:
        """Create a new playlist."""
        try:
            result = self.client.table("playlists").insert({
                "name": name,
                "creator_user_id": user_id
            }).execute()
            if result.data:
                return result.data[0]['id']
            return -1
        except Exception as e:
            logger.error(f"Error creating playlist in Supabase: {e}")
            return -1

    async def get_user_playlists(self, user_id: int) -> List[Dict[str, Any]]:
        """Get playlists for a user."""
        try:
            result = self.client.table("playlists").select("*").eq("creator_user_id", user_id).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting user playlists from Supabase: {e}")
            return []

    async def get_playlist_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get playlist by name."""
        try:
            result = self.client.table("playlists").select("*").eq("name", name).execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting playlist by name from Supabase: {e}")
            return None

    async def get_playlist_tracks(self, playlist_id: int) -> List[Dict[str, Any]]:
        """Get tracks in a playlist."""
        try:
            result = self.client.table("playlist_tracks").select("*").eq("playlist_id", playlist_id).order("position").execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting playlist tracks from Supabase: {e}")
            return []

    async def add_track_to_playlist(self, playlist_id: int, track_id: str, added_by: int) -> bool:
        """Add a track to a playlist."""
        try:
            # Get max position
            tracks = await self.get_playlist_tracks(playlist_id)
            pos = len(tracks) + 1

            self.client.table("playlist_tracks").insert({
                "playlist_id": playlist_id,
                "jamendo_track_id": track_id,
                "position": pos,
                "added_by": added_by
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Error adding track to playlist in Supabase: {e}")
            return False

    async def remove_track_from_playlist(self, playlist_id: int, position: int) -> bool:
        """Remove a track from a playlist by position."""
        try:
            self.client.table("playlist_tracks").delete().match({"playlist_id": playlist_id, "position": position}).execute()
            return True
        except Exception as e:
            logger.error(f"Error removing track from playlist in Supabase: {e}")
            return False

    async def toggle_playlist_collab(self, playlist_id: int, is_collab: bool) -> bool:
        """Toggle collaborative mode for a playlist."""
        try:
            self.client.table("playlists").update({"is_collaborative": is_collab}).eq("id", playlist_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error toggling playlist collab in Supabase: {e}")
            return False

    async def save_jamendo_token(self, user_id: int, token: Dict[str, Any]) -> bool:
        """Save Jamendo token for user in playlists table."""
        try:
            self.client.table("playlists").update({"jamendo_token": token}).eq("creator_user_id", user_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error saving jamendo token in Supabase: {e}")
            return False

    async def get_jamendo_token(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get Jamendo token for a user."""
        try:
            result = self.client.table("playlists").select("jamendo_token").eq("creator_user_id", user_id).neq("jamendo_token", "null").limit(1).execute()
            if result.data and result.data[0].get('jamendo_token'):
                return result.data[0]['jamendo_token']
            return None
        except Exception as e:
            logger.error(f"Error getting jamendo token from Supabase: {e}")
            return None


# Global instance
supabase_db: Optional[SupabaseDatabase] = None




def init_supabase(url: str, key: str):
    """Initialize Supabase database."""
    global supabase_db
    supabase_db = SupabaseDatabase(url, key)
    logger.info("Supabase database initialized")

    # Radio Shows Implementation for Supabase
    async def create_radio_show(self, chat_id: int, host_user_id: int, show_name: str, description: str, day: int, time: str, genre: str, duration: int) -> int:
        """Create a new radio show."""
        try:
            data = {
                "chat_id": chat_id,
                "host_user_id": host_user_id,
                "show_name": show_name,
                "description": description,
                "schedule_day_of_week": day,
                "schedule_time": time,
                "genre_tags": genre,
                "duration_minutes": duration,
                "is_active": True
            }
            result = self.client.table("radio_shows").insert(data).execute()
            if result.data:
                return result.data[0].get("id", -1)
            return -1
        except Exception as e:
            logger.error(f"Error creating radio show in Supabase: {e}")
            return -1

    async def add_track_to_show(self, show_id: int, track_id: int, added_by: int) -> bool:
        """Add a track to a radio show."""
        try:
            # Get current max position
            result = self.client.table("show_tracks").select("position").eq("show_id", show_id).order("position", desc=True).limit(1).execute()
            pos = 0
            if result.data and len(result.data) > 0:
                pos = result.data[0].get("position", 0)

            data = {
                "show_id": show_id,
                "jamendo_track_id": track_id,
                "position": pos + 1,
                "added_by": added_by
            }
            self.client.table("show_tracks").insert(data).execute()
            return True
        except Exception as e:
            logger.error(f"Error adding track to show in Supabase: {e}")
            return False

    async def get_upcoming_shows(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get all upcoming shows for a chat."""
        try:
            result = self.client.table("radio_shows").select("*").eq("chat_id", chat_id).eq("is_active", True).order("schedule_day_of_week").order("schedule_time").execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting upcoming shows from Supabase: {e}")
            return []

    async def get_show_tracks(self, show_id: int) -> List[Dict[str, Any]]:
        """Get all tracks for a radio show."""
        try:
            result = self.client.table("show_tracks").select("*").eq("show_id", show_id).order("position").execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting show tracks from Supabase: {e}")
            return []

    async def get_shows_by_time(self, day: int, time: str) -> List[Dict[str, Any]]:
        """Get all shows scheduled for a specific time."""
        try:
            result = self.client.table("radio_shows").select("*").eq("schedule_day_of_week", day).eq("schedule_time", time).eq("is_active", True).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting shows by time from Supabase: {e}")
            return []

    async def delete_show(self, show_id: int) -> bool:
        """Delete a radio show."""
        try:
            self.client.table("show_tracks").delete().eq("show_id", show_id).execute()
            self.client.table("radio_shows").delete().eq("id", show_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting radio show in Supabase: {e}")
            return False

    async def get_past_shows(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get past shows for a chat."""
        try:
            result = self.client.table("radio_shows").select("*").eq("chat_id", chat_id).eq("is_active", False).order("created_at", desc=True).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting past shows from Supabase: {e}")
            return []

    async def set_show_inactive(self, show_id: int) -> bool:
        """Mark a show as inactive (past)."""
        try:
            self.client.table("radio_shows").update({"is_active": False}).eq("id", show_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error setting show inactive in Supabase: {e}")
            return False

    from types import MethodType
    supabase_db.create_radio_show = MethodType(create_radio_show, supabase_db)
    supabase_db.add_track_to_show = MethodType(add_track_to_show, supabase_db)
    supabase_db.get_upcoming_shows = MethodType(get_upcoming_shows, supabase_db)
    supabase_db.get_show_tracks = MethodType(get_show_tracks, supabase_db)
    supabase_db.get_shows_by_time = MethodType(get_shows_by_time, supabase_db)
    supabase_db.delete_show = MethodType(delete_show, supabase_db)
    supabase_db.get_past_shows = MethodType(get_past_shows, supabase_db)
    supabase_db.set_show_inactive = MethodType(set_show_inactive, supabase_db)
