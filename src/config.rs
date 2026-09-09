use serde::{Deserialize, Serialize};
use std::env;
use std::path::PathBuf;
use std::time::Duration;
use tracing::info;
use tracing_subscriber::{fmt, EnvFilter};

pub fn init_logger() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| {
        EnvFilter::new(
            "info,brook_music_bot=debug,h2=warn,rustls=warn,reqwest=warn,hyper=warn,sqlx=warn",
        )
    });

    fmt()
        .with_env_filter(filter)
        .with_target(true)
        .with_thread_ids(true)
        .with_thread_names(true)
        .with_line_number(true)
        .with_file(true)
        .pretty()
        .init();
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Config {
    pub bot_token: Option<String>,
    pub owner_id: Option<i64>,
    pub admin_password: Option<String>,

    pub port: Option<u16>,
    pub metrics_http_enabled: bool,
    pub metrics_http_token: Option<String>,
    pub metrics_prometheus_enabled: bool,

    pub music_microservice_url: Option<String>,

    pub spotify_client_id: Option<String>,
    pub spotify_client_secret: Option<String>,
    pub soundcloud_client_id: Option<String>,
    pub invidious_instances: Vec<String>,
    pub active_invidious_instances: Vec<String>,
    pub piped_instances: Vec<String>,
    pub active_piped_instances: Vec<String>,
    pub resolver_cache_ttl_secs: u64,
    pub stream_cache_ttl_secs: u64,
    pub youtube_enabled: bool,
    pub yt_dlp_enabled: bool,
    pub yt_dlp_binary: String,
    pub yt_dlp_timeout_secs: u64,

    pub max_direct_stream_mb: u64,
    pub allowed_direct_hosts: Vec<String>,

    pub max_queue_size: usize,
    pub default_volume: u32,
    pub command_cooldown: u64,
    pub max_concurrent_resolutions: usize,

    pub tg_api_id: Option<i32>,
    pub tg_api_hash: Option<String>,
    pub assistant_session: String,
    pub assistant_session_string: Option<String>,

    pub nvidia_nim_api_key: Option<String>,
    pub nvidia_nim_base_url: String,
    pub nvidia_nim_model: String,

    pub database_url: Option<String>,
    pub mongodb_uri: Option<String>,
    pub heroku_app_name: Option<String>,
}

impl std::fmt::Debug for Config {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Config")
            .field("bot_token", &self.bot_token.as_ref().map(|_| "[REDACTED]"))
            .field("owner_id", &self.owner_id)
            .field(
                "admin_password",
                &self.admin_password.as_ref().map(|_| "[REDACTED]"),
            )
            .field("port", &self.port)
            .field("metrics_http_enabled", &self.metrics_http_enabled)
            .field(
                "metrics_http_token",
                &self.metrics_http_token.as_ref().map(|_| "[REDACTED]"),
            )
            .field(
                "metrics_prometheus_enabled",
                &self.metrics_prometheus_enabled,
            )
            .field("music_microservice_url", &self.music_microservice_url)
            .field(
                "spotify_client_id",
                &self.spotify_client_id.as_ref().map(|_| "[REDACTED]"),
            )
            .field(
                "spotify_client_secret",
                &self.spotify_client_secret.as_ref().map(|_| "[REDACTED]"),
            )
            .field(
                "soundcloud_client_id",
                &self.soundcloud_client_id.as_ref().map(|_| "[REDACTED]"),
            )
            .field("invidious_instances", &self.invidious_instances)
            .field(
                "active_invidious_instances",
                &self.active_invidious_instances,
            )
            .field("piped_instances", &self.piped_instances)
            .field("active_piped_instances", &self.active_piped_instances)
            .field("resolver_cache_ttl_secs", &self.resolver_cache_ttl_secs)
            .field("stream_cache_ttl_secs", &self.stream_cache_ttl_secs)
            .field("youtube_enabled", &self.youtube_enabled)
            .field("yt_dlp_enabled", &self.yt_dlp_enabled)
            .field("yt_dlp_binary", &self.yt_dlp_binary)
            .field("yt_dlp_timeout_secs", &self.yt_dlp_timeout_secs)
            .field("max_direct_stream_mb", &self.max_direct_stream_mb)
            .field("allowed_direct_hosts", &self.allowed_direct_hosts)
            .field("max_queue_size", &self.max_queue_size)
            .field("default_volume", &self.default_volume)
            .field("command_cooldown", &self.command_cooldown)
            .field(
                "max_concurrent_resolutions",
                &self.max_concurrent_resolutions,
            )
            .field("tg_api_id", &self.tg_api_id)
            .field(
                "tg_api_hash",
                &self.tg_api_hash.as_ref().map(|_| "[REDACTED]"),
            )
            .field("assistant_session", &self.assistant_session)
            .field(
                "assistant_session_string",
                &self.assistant_session_string.as_ref().map(|_| "[REDACTED]"),
            )
            .field(
                "nvidia_nim_api_key",
                &self.nvidia_nim_api_key.as_ref().map(|_| "[REDACTED]"),
            )
            .field("nvidia_nim_base_url", &self.nvidia_nim_base_url)
            .field("nvidia_nim_model", &self.nvidia_nim_model)
            .finish()
    }
}

impl Config {
    pub async fn load() -> Self {
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

        let bot_token = env::var("BOT_TOKEN")
            .or_else(|_| env::var("TELEGRAM_BOT_TOKEN"))
            .or_else(|_| env::var("TG_BOT_TOKEN"))
            .ok()
            .filter(|v| !v.contains("your_"));

        // Fast-boot: skip the expensive instance health-check ping at startup.
        // Instances are checked lazily on first use instead.
        let _skip_instance_check = env::var("SKIP_INSTANCE_CHECK")
            .unwrap_or_default()
            .parse()
            .unwrap_or(false);

        let owner_id = env::var("OWNER_ID")
            .ok()
            .and_then(|v| v.parse::<i64>().ok());
        let admin_password = env::var("ADMIN_PASSWORD").ok().filter(|v| !v.is_empty());
        let port = env::var("PORT").ok().and_then(|v| v.parse::<u16>().ok());

        let metrics_http_enabled = env::var("METRICS_HTTP_ENABLED")
            .unwrap_or_default()
            .parse()
            .unwrap_or(false);
        let metrics_http_token = env::var("METRICS_HTTP_TOKEN")
            .ok()
            .filter(|v| !v.is_empty());
        let metrics_prometheus_enabled = env::var("METRICS_PROMETHEUS_ENABLED")
            .unwrap_or_default()
            .parse()
            .unwrap_or(false);

        let music_microservice_url = env::var("MUSIC_MICROSERVICE_URL").ok().filter(|v| {
            !v.is_empty()
                && !v.contains("your_")
                && !v.contains("example.com")
                && !v.contains("replace")
        });

        let spotify_client_id = env::var("SPOTIFY_CLIENT_ID")
            .ok()
            .filter(|v| !v.is_empty() && !v.contains("your_"));
        let spotify_client_secret = env::var("SPOTIFY_CLIENT_SECRET")
            .ok()
            .filter(|v| !v.is_empty() && !v.contains("your_"));
        let soundcloud_client_id = env::var("SOUNDCLOUD_CLIENT_ID")
            .ok()
            .filter(|v| !v.is_empty() && !v.contains("your_"));

        let invidious_instances = env::var("INVIDIOUS_INSTANCES")
            .unwrap_or_else(|_| "invidious.flokinet.to,invidious.snopyta.org,invidious.bkp.snopyta.org,invidious.privacydev.net,yt.artemislena.eu,invidious.lunar.icu,invidious.privacydev.net,inv.vern.cc,invidious.kavin.rocks,invidious.projectsegfau.lt,invidious.nerdvpn.de,vid.puffyan.us,inv.nadeko.net,invidious.f5.si,iv.ggtyler.dev".to_string())
            .split(',')
            .map(|s| s.trim().trim_start_matches("https://").to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let piped_instances = env::var("PIPED_INSTANCES")
            .unwrap_or_else(|_| "piped.kavin.rocks,piped.privacydev.net,piped.moomoo.me,piped.esmailelbob.xyz,pipedapi.kavin.rocks,pipedapi.tokhmi.xyz,piped-api.garudalinux.org,pipedapi.reallyaweso.me,piped.moomoo.me,piped.privacydev.net,piped-api.lunar.icu,piped-api.projectsegfau.lt,piped-api.privacydev.net,piped-api.vern.cc".to_string())
            .split(',')
            .map(|s| s.trim().trim_start_matches("https://").to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let resolver_cache_ttl_secs = env::var("RESOLVER_CACHE_TTL_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(300);
        let stream_cache_ttl_secs = env::var("RESOLVER_STREAM_CACHE_TTL_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(60);
        let youtube_enabled = env::var("YOUTUBE_ENABLED")
            .unwrap_or_else(|_| "true".to_string())
            .parse()
            .unwrap_or(true);
        let yt_dlp_enabled = env::var("YT_DLP_ENABLED")
            .unwrap_or_else(|_| "true".to_string())
            .parse()
            .unwrap_or(true);
        let yt_dlp_binary = env::var("YT_DLP_BINARY").unwrap_or_else(|_| "yt-dlp".to_string());
        let yt_dlp_timeout_secs = env::var("YT_DLP_TIMEOUT_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(20);
        let max_direct_stream_mb = env::var("MAX_DIRECT_STREAM_MB")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(100);

        let allowed_direct_hosts = env::var("ALLOWED_DIRECT_HOSTS")
            .unwrap_or_default()
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let max_queue_size = env::var("MAX_QUEUE_SIZE")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(100);
        let default_volume = env::var("DEFAULT_VOLUME")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(100);
        let command_cooldown = env::var("COMMAND_COOLDOWN")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(3);
        let max_concurrent_resolutions = env::var("MAX_CONCURRENT_RESOLUTIONS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(4);

        let tg_api_id = env::var("TG_API_ID")
            .ok()
            .and_then(|v| v.parse::<i32>().ok());
        let tg_api_hash = env::var("TG_API_HASH")
            .ok()
            .filter(|v| !v.is_empty() && !v.contains("your_"));
        let assistant_session =
            env::var("ASSISTANT_SESSION").unwrap_or_else(|_| "assistant.session".to_string());
        let assistant_session_string = env::var("ASSISTANT_SESSION_STRING")
            .ok()
            .filter(|v| !v.is_empty());

        let nvidia_nim_api_key = env::var("NVIDIA_NIM_API_KEY")
            .or_else(|_| env::var("NVIDIA_API_KEY"))
            .ok()
            .filter(|v| !v.is_empty() && !v.contains("your_"));
        let nvidia_nim_base_url = env::var("NVIDIA_NIM_BASE_URL")
            .unwrap_or_else(|_| "https://integrate.api.nvidia.com/v1".to_string());
        let nvidia_nim_model = env::var("NVIDIA_NIM_MODEL")
            .unwrap_or_else(|_| "meta/llama-3.1-70b-instruct".to_string());

        let database_url = env::var("DATABASE_URL").ok().filter(|v| !v.is_empty());
        let mongodb_uri = env::var("MONGODB_URI").ok().filter(|v| !v.is_empty());
        let heroku_app_name = env::var("HEROKU_APP_NAME").ok().filter(|v| !v.is_empty());

        let config = Self {
            bot_token,
            owner_id,
            admin_password,
            port,
            metrics_http_enabled,
            metrics_http_token,
            metrics_prometheus_enabled,
            music_microservice_url,
            spotify_client_id,
            spotify_client_secret,
            soundcloud_client_id,
            invidious_instances,
            active_invidious_instances: Vec::new(),
            piped_instances,
            active_piped_instances: Vec::new(),
            resolver_cache_ttl_secs,
            stream_cache_ttl_secs,
            youtube_enabled,
            yt_dlp_enabled,
            yt_dlp_binary,
            yt_dlp_timeout_secs,
            max_direct_stream_mb,
            allowed_direct_hosts,
            max_queue_size,
            default_volume,
            command_cooldown,
            max_concurrent_resolutions,
            tg_api_id,
            tg_api_hash,
            assistant_session,
            assistant_session_string,
            nvidia_nim_api_key,
            nvidia_nim_base_url,
            nvidia_nim_model,
            database_url,
            mongodb_uri,
            heroku_app_name,
        };

        // Fast-boot: run instance health checks in the background, don't block startup.
        // Instances are also checked lazily on first use when SKIP_INSTANCE_CHECK is set.
        let cfg_mutex = tokio::sync::Mutex::new(config.clone());
        tokio::spawn(async move {
            if env::var("SKIP_INSTANCE_CHECK")
                .unwrap_or_default()
                .parse()
                .unwrap_or(false)
            {
                return;
            }
            let mut cfg = cfg_mutex.lock().await;
            cfg.check_instances_light().await;
        });
        config
    }

    /// Light-weight instance check: single attempt per instance, no retries, runs in background.
    async fn check_instances_light(&mut self) {
        let client = reqwest::Client::new();
        let timeout = Duration::from_secs(3);

        let mut active_invidious = Vec::new();
        let mut active_piped = Vec::new();

        for instance in &self.invidious_instances {
            let ping_url = format!("https://{}/api/v1/ping", instance);
            if client.get(&ping_url).timeout(timeout).send().await.is_ok() {
                active_invidious.push(instance.clone());
                info!("✅ Invidious instance reachable: {}", instance);
            }
        }
        for instance in &self.piped_instances {
            let url = format!("https://{}/api/v1/search?q=test", instance);
            if client.get(&url).timeout(timeout).send().await.is_ok() {
                active_piped.push(instance.clone());
                info!("✅ Piped instance reachable: {}", instance);
            }
        }

        self.active_invidious_instances = active_invidious;
        self.active_piped_instances = active_piped;
    }
}
