use std::env;
use std::path::PathBuf;
use serde::{Deserialize, Serialize};
use tracing::{info, warn};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub telegram_enabled: bool,
    pub api_id: Option<i32>,
    pub api_hash: Option<String>,
    pub bot_token: Option<String>,
    pub bot_id: Option<i64>,
    pub bot_username: Option<String>,
    pub bot_username_alt: Option<String>,
    pub admin_password: Option<String>,
    pub owner_id: Option<i64>,

    pub session_string_1: Option<String>,
    pub session_string_2: Option<String>,
    pub session_string_3: Option<String>,
    pub session_string_4: Option<String>,
    pub session_string_5: Option<String>,

    pub session_file_path_1: Option<String>,
    pub session_file_path_2: Option<String>,
    pub session_file_path_3: Option<String>,
    pub session_file_path_4: Option<String>,
    pub session_file_path_5: Option<String>,

    pub mongo_uri: String,
    pub sqlite_cache_path: String,
    pub sqlite_db_path: String,
    pub neon_database_url: Option<String>,
    pub genius_token: Option<String>,
    pub log_group_id: Option<i64>,
    pub metrics_http_enabled: bool,
    pub metrics_http_token: Option<String>,
    pub metrics_prometheus_enabled: bool,
    pub webhook_url: Option<String>,
    pub webhook_path: String,
    pub port: Option<u16>,

    pub max_queue_size: usize,
    pub default_volume: u32,
    pub command_cooldown: u64,
    pub audio_quality: String,
    pub audio_bitrate: u32,
    pub audio_loudnorm: bool,
    pub legal_sources_first: bool,
    pub music_microservice_url: Option<String>,
    pub music_provider_priority: String,
    pub np_autoclean_delay: u64,
    pub search_msg_autoclean: u64,
    pub np_update_interval: u64,
    pub vc_play_timeout: u64,
    pub auto_start_vc: bool,
    pub auto_start_vc_title: String,
}

impl Config {
    pub fn load() -> Self {
        // Try loading env files in order
        let env_candidates = vec![
            PathBuf::from("../.env.local"),
            PathBuf::from("./.env.local"),
            PathBuf::from("../.env"),
            PathBuf::from("./.env"),
        ];

        for candidate in env_candidates {
            if candidate.exists() {
                if let Ok(path_str) = candidate.to_str().ok_or(()) {
                    info!("Loading environment file: {}", path_str);
                    let _ = dotenvy::from_path(&candidate);
                }
            }
        }

        let api_id = env::var("API_ID")
            .or_else(|_| env::var("TELEGRAM_API_ID"))
            .or_else(|_| env::var("TG_API_ID"))
            .ok()
            .and_then(|v| v.parse::<i32>().ok());

        let api_hash = env::var("API_HASH")
            .or_else(|_| env::var("TELEGRAM_API_HASH"))
            .or_else(|_| env::var("TG_API_HASH"))
            .ok()
            .filter(|v| !v.contains("your_"));

        let bot_token = env::var("BOT_TOKEN")
            .or_else(|_| env::var("TELEGRAM_BOT_TOKEN"))
            .or_else(|_| env::var("TG_BOT_TOKEN"))
            .ok()
            .filter(|v| !v.contains("your_"));

        let admin_password = env::var("ADMIN_PASSWORD").ok().filter(|v| !v.is_empty());
        let owner_id = env::var("OWNER_ID").ok().and_then(|v| v.parse::<i64>().ok());
        let log_group_id = env::var("LOG_GROUP_ID").ok().and_then(|v| v.parse::<i64>().ok());

        let port = env::var("PORT").ok().and_then(|v| v.parse::<u16>().ok());

        let config = Self {
            telegram_enabled: api_id.is_some() && api_hash.is_some() && bot_token.is_some(),
            api_id,
            api_hash,
            bot_token,
            bot_id: env::var("BOT_ID").ok().and_then(|v| v.parse::<i64>().ok()),
            bot_username: env::var("BOT_USERNAME").ok(),
            bot_username_alt: env::var("BOT_USERNAME_ALT").ok(),
            admin_password,
            owner_id,

            session_string_1: env::var("SESSION_STRING_1").ok().filter(|v| !v.is_empty()),
            session_string_2: env::var("SESSION_STRING_2").ok().filter(|v| !v.is_empty()),
            session_string_3: env::var("SESSION_STRING_3").ok().filter(|v| !v.is_empty()),
            session_string_4: env::var("SESSION_STRING_4").ok().filter(|v| !v.is_empty()),
            session_string_5: env::var("SESSION_STRING_5").ok().filter(|v| !v.is_empty()),

            session_file_path_1: env::var("SESSION_FILE_PATH_1").ok(),
            session_file_path_2: env::var("SESSION_FILE_PATH_2").ok(),
            session_file_path_3: env::var("SESSION_FILE_PATH_3").ok(),
            session_file_path_4: env::var("SESSION_FILE_PATH_4").ok(),
            session_file_path_5: env::var("SESSION_FILE_PATH_5").ok(),

            mongo_uri: env::var("MONGO_URI").unwrap_or_else(|_| "mongodb://mongo:27017/musicbot".into()),
            sqlite_cache_path: env::var("SQLITE_CACHE_PATH").unwrap_or_else(|_| "./data/cache.db".into()),
            sqlite_db_path: env::var("SQLITE_DB_PATH").unwrap_or_else(|_| "./data/database.db".into()),
            neon_database_url: env::var("NEON_DATABASE_URL").ok().filter(|v| !v.is_empty()),
            genius_token: env::var("GENIUS_TOKEN").ok(),
            log_group_id,
            metrics_http_enabled: env::var("METRICS_HTTP_ENABLED").unwrap_or_default().parse().unwrap_or(false),
            metrics_http_token: env::var("METRICS_HTTP_TOKEN").ok(),
            metrics_prometheus_enabled: env::var("METRICS_PROMETHEUS_ENABLED").unwrap_or_default().parse().unwrap_or(false),
            webhook_url: env::var("WEBHOOK_URL").ok(),
            webhook_path: env::var("WEBHOOK_PATH").unwrap_or_else(|_| "/webhook".into()),
            port,

            max_queue_size: env::var("MAX_QUEUE_SIZE").ok().and_then(|v| v.parse().ok()).unwrap_or(100),
            default_volume: env::var("DEFAULT_VOLUME").ok().and_then(|v| v.parse().ok()).unwrap_or(100),
            command_cooldown: env::var("COMMAND_COOLDOWN").ok().and_then(|v| v.parse().ok()).unwrap_or(3),
            audio_quality: env::var("AUDIO_QUALITY").unwrap_or_else(|_| "high".into()),
            audio_bitrate: env::var("AUDIO_BITRATE").ok().and_then(|v| v.parse().ok()).unwrap_or(192),
            audio_loudnorm: env::var("AUDIO_LOUDNORM").unwrap_or_default().parse().unwrap_or(true),
            legal_sources_first: env::var("LEGAL_SOURCES_FIRST").unwrap_or_default().parse().unwrap_or(true),
            music_microservice_url: env::var("MUSIC_MICROSERVICE_URL").ok().filter(|v| !v.is_empty()),
            music_provider_priority: env::var("MUSIC_PROVIDER_PRIORITY").unwrap_or_else(|_| "youtube,soundcloud,apple_music".into()),
            np_autoclean_delay: env::var("NP_AUTOCLEAN_DELAY").ok().and_then(|v| v.parse().ok()).unwrap_or(30),
            search_msg_autoclean: env::var("SEARCH_MSG_AUTOCLEAN").ok().and_then(|v| v.parse().ok()).unwrap_or(8),
            np_update_interval: env::var("NP_UPDATE_INTERVAL").ok().and_then(|v| v.parse().ok()).unwrap_or(3),
            vc_play_timeout: env::var("VC_PLAY_TIMEOUT").ok().and_then(|v| v.parse().ok()).unwrap_or(20),
            auto_start_vc: env::var("AUTO_START_VC").unwrap_or_default().parse().unwrap_or(true),
            auto_start_vc_title: env::var("AUTO_START_VC_TITLE").unwrap_or_else(|_| "Music Bot Live".into()),
        };

        if !config.telegram_enabled {
            warn!("Telegram credentials missing or incomplete (API_ID, API_HASH, BOT_TOKEN).");
        }

        config
    }

    pub fn session_strings(&self) -> Vec<String> {
        [
            &self.session_string_1,
            &self.session_string_2,
            &self.session_string_3,
            &self.session_string_4,
            &self.session_string_5,
        ]
        .iter()
        .filter_map(|s| s.as_ref())
        .cloned()
        .collect()
    }
}
