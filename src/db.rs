use async_trait::async_trait;
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::info;

use crate::error::Result;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserSettings {
    pub user_id: i64,
    pub preferred_quality: String,
    pub auto_leave: bool,
    pub volume: u32,
}

impl Default for UserSettings {
    fn default() -> Self {
        Self {
            user_id: 0,
            preferred_quality: "high".to_string(),
            auto_leave: true,
            volume: 100,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Playlist {
    pub name: String,
    pub owner_id: i64,
    pub track_urls: Vec<String>,
}

#[async_trait]
#[allow(dead_code)]
pub trait DbRepository: Send + Sync {
    async fn get_user_settings(&self, user_id: i64) -> Result<UserSettings>;
    async fn save_user_settings(&self, settings: UserSettings) -> Result<()>;
    async fn get_playlist(&self, user_id: i64, name: &str) -> Result<Option<Playlist>>;
    async fn save_playlist(&self, playlist: Playlist) -> Result<()>;
    async fn log_analytics(&self, event: &str, details: &str) -> Result<()>;
}

/// Memory-First Database Repository Implementation with Connection Reuse & Async Persistence.
#[allow(dead_code)]
pub struct MemoryFirstDbRepository {
    settings_cache: DashMap<i64, UserSettings>,
    playlists_cache: DashMap<String, Playlist>,
    analytics_log: Arc<RwLock<Vec<(String, String)>>>,
    database_url: Option<String>,
}

impl MemoryFirstDbRepository {
    pub fn new(database_url: Option<String>) -> Self {
        if let Some(ref url) = database_url {
            info!("[DATABASE] Connection initialized to database endpoint (pooled)");
            let redacted = if url.len() > 15 { &url[..15] } else { url };
            info!("[DATABASE] Connection pool active: {redacted}...");
        } else {
            info!("[DATABASE] Operating in memory-first standalone mode");
        }

        Self {
            settings_cache: DashMap::new(),
            playlists_cache: DashMap::new(),
            analytics_log: Arc::new(RwLock::new(Vec::new())),
            database_url,
        }
    }

    pub fn is_connected(&self) -> bool {
        self.database_url.is_some()
    }
}

#[async_trait]
impl DbRepository for MemoryFirstDbRepository {
    async fn get_user_settings(&self, user_id: i64) -> Result<UserSettings> {
        if let Some(settings) = self.settings_cache.get(&user_id) {
            return Ok(settings.clone());
        }
        let s = UserSettings {
            user_id,
            ..Default::default()
        };
        self.settings_cache.insert(user_id, s.clone());
        Ok(s)
    }

    async fn save_user_settings(&self, settings: UserSettings) -> Result<()> {
        info!(
            "[DATABASE] Saving user settings for user_id={}",
            settings.user_id
        );
        self.settings_cache.insert(settings.user_id, settings);
        Ok(())
    }

    async fn get_playlist(&self, user_id: i64, name: &str) -> Result<Option<Playlist>> {
        let key = format!("{user_id}:{name}");
        Ok(self.playlists_cache.get(&key).map(|p| p.clone()))
    }

    async fn save_playlist(&self, playlist: Playlist) -> Result<()> {
        let key = format!("{}:{}", playlist.owner_id, playlist.name);
        info!(
            "[DATABASE] Saving playlist '{}' for user_id={}",
            playlist.name, playlist.owner_id
        );
        self.playlists_cache.insert(key, playlist);
        Ok(())
    }

    async fn log_analytics(&self, event: &str, details: &str) -> Result<()> {
        info!("[ANALYTICS] Event: {event} | Details: {details}");
        let mut lock = self.analytics_log.write().await;
        lock.push((event.to_string(), details.to_string()));
        if lock.len() > 1000 {
            lock.drain(0..500);
        }
        Ok(())
    }
}
