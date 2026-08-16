use sqlx::{sqlite::SqlitePoolOptions, Pool, Sqlite, Row};
use std::path::Path;
use tracing::info;
use serde_json::Value;
use crate::error::Result;

#[derive(Debug, Clone)]
pub struct GroupModel {
    pub id: i64,
    pub title: String,
    pub lang: String,
    pub is_active: bool,
    pub settings: Value,
}

#[derive(Debug, Clone)]
pub struct PlaylistModel {
    pub id: i64,
    pub name: String,
    pub creator_user_id: i64,
    pub is_collaborative: bool,
    pub is_public: bool,
}

#[derive(Clone)]
pub struct Database {
    pool: Pool<Sqlite>,
}

impl Database {
    pub async fn connect(db_path: &str) -> Result<Self> {
        let path = Path::new(db_path);
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await.ok();
        }

        let connection_str = format!("sqlite:{}?mode=rwc", db_path);
        let pool = SqlitePoolOptions::new()
            .max_connections(10)
            .connect(&connection_str)
            .await?;

        let db = Self { pool };
        db.init_tables().await?;
        info!("SQLite database connected and fully initialized at: {}", db_path);

        Ok(db)
    }

    async fn init_tables(&self) -> Result<()> {
        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                title TEXT,
                lang TEXT DEFAULT 'en',
                is_active INTEGER DEFAULT 1,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settings TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS sudousers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS gbanned (
                id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_by INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS groupbans (
                chat_id INTEGER,
                user_id INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS quiz_scores (
                user_id INTEGER PRIMARY KEY,
                score INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS global_music_index (
                query_key TEXT PRIMARY KEY,
                jamendo_track_id INTEGER,
                title TEXT,
                artist TEXT,
                duration INTEGER,
                thumbnail_url TEXT,
                audio_url TEXT,
                metadata TEXT DEFAULT '{}',
                sources TEXT DEFAULT '[]',
                last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS mini_app_sessions (
                user_id INTEGER PRIMARY KEY,
                recent_tracks TEXT DEFAULT '[]',
                preferences TEXT DEFAULT '{}',
                last_chat_id INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS radio_shows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                host_user_id INTEGER,
                show_name TEXT,
                description TEXT,
                schedule_day_of_week INTEGER,
                schedule_time TEXT,
                genre_tags TEXT,
                duration_minutes INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS show_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id INTEGER,
                jamendo_track_id INTEGER,
                position INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(show_id) REFERENCES radio_shows(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS lobby_snapshots (
                chat_id INTEGER PRIMARY KEY,
                now_playing TEXT,
                queue TEXT DEFAULT '[]',
                status TEXT DEFAULT 'idle',
                position_seconds INTEGER DEFAULT 0,
                participants TEXT DEFAULT '[]',
                version INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                creator_user_id INTEGER NOT NULL,
                jamendo_playlist_id TEXT,
                is_collaborative INTEGER DEFAULT 0,
                is_public INTEGER DEFAULT 0,
                jamendo_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER,
                jamendo_track_id TEXT NOT NULL,
                position INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
            );
            "#
        )
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    pub async fn get_group(&self, chat_id: i64) -> Result<GroupModel> {
        let row = sqlx::query("SELECT id, title, lang, is_active, settings FROM groups WHERE id = ?")
            .bind(chat_id)
            .fetch_optional(&self.pool)
            .await?;

        if let Some(r) = row {
            let settings_str: String = r.get("settings");
            let settings: Value = serde_json::from_str(&settings_str).unwrap_or(serde_json::json!({}));
            Ok(GroupModel {
                id: r.get("id"),
                title: r.get::<Option<String>, _>("title").unwrap_or_default(),
                lang: r.get::<Option<String>, _>("lang").unwrap_or_else(|| "en".into()),
                is_active: r.get::<i32, _>("is_active") == 1,
                settings,
            })
        } else {
            let default_settings = serde_json::json!({
                "play_on_join": true,
                "max_queue": 100,
                "vol_default": 100,
                "loop_mode": "none",
                "quality": "high",
                "thumb_mode": true
            });
            let settings_str = serde_json::to_string(&default_settings).unwrap();

            sqlx::query("INSERT INTO groups (id, title, is_active, settings) VALUES (?, ?, 1, ?)")
                .bind(chat_id)
                .bind("")
                .bind(settings_str)
                .execute(&self.pool)
                .await?;

            Ok(GroupModel {
                id: chat_id,
                title: "".into(),
                lang: "en".into(),
                is_active: true,
                settings: default_settings,
            })
        }
    }

    pub async fn create_playlist(&self, name: &str, creator_user_id: i64) -> Result<i64> {
        let result = sqlx::query("INSERT INTO playlists (name, creator_user_id) VALUES (?, ?)")
            .bind(name)
            .bind(creator_user_id)
            .execute(&self.pool)
            .await?;

        Ok(result.last_insert_rowid())
    }

    pub async fn get_user_playlists(&self, creator_user_id: i64) -> Result<Vec<PlaylistModel>> {
        let rows = sqlx::query("SELECT id, name, creator_user_id, is_collaborative, is_public FROM playlists WHERE creator_user_id = ?")
            .bind(creator_user_id)
            .fetch_all(&self.pool)
            .await?;

        let mut list = Vec::new();
        for r in rows {
            list.push(PlaylistModel {
                id: r.get("id"),
                name: r.get("name"),
                creator_user_id: r.get("creator_user_id"),
                is_collaborative: r.get::<i32, _>("is_collaborative") == 1,
                is_public: r.get::<i32, _>("is_public") == 1,
            });
        }
        Ok(list)
    }

    pub async fn add_track_to_playlist(&self, playlist_id: i64, track_id: &str, added_by: i64) -> Result<()> {
        sqlx::query("INSERT INTO playlist_tracks (playlist_id, jamendo_track_id, added_by) VALUES (?, ?, ?)")
            .bind(playlist_id)
            .bind(track_id)
            .bind(added_by)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn is_sudo(&self, user_id: i64) -> Result<bool> {
        let row = sqlx::query("SELECT id FROM sudousers WHERE id = ?")
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.is_some())
    }

    pub async fn add_sudo(&self, user_id: i64, name: Option<&str>, added_by: i64) -> Result<()> {
        sqlx::query("INSERT OR REPLACE INTO sudousers (id, name, added_by) VALUES (?, ?, ?)")
            .bind(user_id)
            .bind(name)
            .bind(added_by)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn del_sudo(&self, user_id: i64) -> Result<()> {
        sqlx::query("DELETE FROM sudousers WHERE id = ?")
            .bind(user_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn is_gbanned(&self, user_id: i64) -> Result<bool> {
        let row = sqlx::query("SELECT id FROM gbanned WHERE id = ?")
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.is_some())
    }

    pub async fn gban(&self, user_id: i64, reason: Option<&str>, banned_by: i64) -> Result<()> {
        sqlx::query("INSERT OR REPLACE INTO gbanned (id, reason, banned_by) VALUES (?, ?, ?)")
            .bind(user_id)
            .bind(reason)
            .bind(banned_by)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn ungban(&self, user_id: i64) -> Result<()> {
        sqlx::query("DELETE FROM gbanned WHERE id = ?")
            .bind(user_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn is_group_banned(&self, chat_id: i64, user_id: i64) -> Result<bool> {
        let row = sqlx::query("SELECT user_id FROM groupbans WHERE chat_id = ? AND user_id = ?")
            .bind(chat_id)
            .bind(user_id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.is_some())
    }

    pub async fn group_ban(&self, chat_id: i64, user_id: i64) -> Result<()> {
        sqlx::query("INSERT OR IGNORE INTO groupbans (chat_id, user_id) VALUES (?, ?)")
            .bind(chat_id)
            .bind(user_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn group_unban(&self, chat_id: i64, user_id: i64) -> Result<()> {
        sqlx::query("DELETE FROM groupbans WHERE chat_id = ? AND user_id = ?")
            .bind(chat_id)
            .bind(user_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn update_quiz_score(&self, user_id: i64, delta: i32) -> Result<i32> {
        let row = sqlx::query(
            "INSERT INTO quiz_scores (user_id, score) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET score = score + ?, updated_at = CURRENT_TIMESTAMP RETURNING score"
        )
        .bind(user_id)
        .bind(delta)
        .bind(delta)
        .fetch_one(&self.pool)
        .await?;

        let score: i32 = row.get("score");
        Ok(score)
    }

    pub async fn get_quiz_leaderboard(&self, limit: i64) -> Result<Vec<(i64, i32)>> {
        let rows = sqlx::query("SELECT user_id, score FROM quiz_scores ORDER BY score DESC LIMIT ?")
            .bind(limit)
            .fetch_all(&self.pool)
            .await?;

        let mut results = Vec::new();
        for row in rows {
            let user_id: i64 = row.get("user_id");
            let score: i32 = row.get("score");
            results.push((user_id, score));
        }

        Ok(results)
    }
}
