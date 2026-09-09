mod ai;
mod commands;
mod config;
mod db;
mod error;
mod media_engine;
mod providers;
mod router;

#[cfg(test)]
mod tests;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::RwLock;
use std::time::Duration;

use axum::body::Body;
use axum::extract::Query;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use serde_json::json;
use teloxide::prelude::*;
use tokio_util::io::ReaderStream;

use crate::ai::AiReceiver;
use crate::commands::{handle_command, BotCommand};
use crate::config::{init_logger, Config};
use crate::db::{DbRepository, MemoryFirstDbRepository};
use crate::media_engine::{
    connect_voice_transport, InMemoryQueueRepository, MediaEngine, PlaybackTransport, TelegramAudioTransport, VoiceChatTransport,
};
use crate::providers::{AppleResolver, DirectResolver, SoundCloudResolver, SpotifyResolver, YouTubeResolver};
use crate::router::{MusicRouter, Platform, Route, SourceAdapter, TrackResolver, UrlResolver, VideoResolver};

async fn stream_handler(Query(params): Query<HashMap<String, String>>) -> impl IntoResponse {
    let video_id = match params.get("yt") {
        Some(id) if !id.is_empty() => id.to_string(),
        _ => return (axum::http::StatusCode::BAD_REQUEST, "Missing yt param").into_response(),
    };

    let url = format!("https://www.youtube.com/watch?v={video_id}");
    tracing::info!(video_id = %video_id, "Piping yt-dlp real-time audio stream over HTTP");

    let child = match tokio::process::Command::new("yt-dlp")
        .args([
            "--no-warnings",
            "--no-playlist",
            "--format",
            "bestaudio",
            "--extract-audio",
            "--audio-format",
            "opus",
            "--audio-quality",
            "0",
            "-o",
            "-",
            &url,
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            tracing::error!(error = %e, "Failed to spawn yt-dlp audio stream process");
            return (axum::http::StatusCode::INTERNAL_SERVER_ERROR, format!("Failed to spawn yt-dlp: {e}")).into_response();
        }
    };

    let stdout = match child.stdout {
        Some(s) => s,
        None => return (axum::http::StatusCode::INTERNAL_SERVER_ERROR, "Failed to capture stdout").into_response(),
    };

    let stream = ReaderStream::new(stdout);
    let body = Body::from_stream(stream);

    axum::response::Response::builder()
        .header("Content-Type", "audio/webm")
        .header("Cache-Control", "no-cache")
        .body(body)
        .unwrap()
}

use axum::extract::State;
use axum::routing::post;
use serde::Deserialize;
use crate::media_engine::{EngineState, LoopMode, PlaybackState, VoiceState};

async fn index_handler() -> Json<serde_json::Value> {
    Json(json!({"service": "Brock Music Bot", "status": "online", "version": "v0.2.0"}))
}

async fn brook_image_handler() -> impl IntoResponse {
    (
        [("Content-Type", "image/png"), ("Cache-Control", "public, max-age=86400")],
        include_bytes!("../assets/brook.png").as_slice(),
    )
}

async fn api_state_handler(
    State(app): State<Arc<AppState>>,
    Query(params): Query<HashMap<String, String>>,
) -> Json<serde_json::Value> {
    let chat_id = params.get("chat_id").and_then(|s| s.parse().ok()).unwrap_or(0);
    let pb = app.media_engine.state(chat_id).await.unwrap_or_else(|_| PlaybackState {
        current: None,
        position_secs: 0,
        is_paused: false,
        loop_mode: LoopMode::Off,
        volume: 100,
        queue_len: 0,
        history_len: 0,
        engine_state: EngineState::Idle,
        voice_state: VoiceState::Disconnected,
        playback_generation: 0,
        vc_generation: 0,
        owner_user_id: None,
        owner_user_name: String::new(),
        session_id: String::new(),
        last_error: None,
        player_message_id: None,
        queue: Vec::new(),
    });

    Json(json!({
        "current": pb.current,
        "position_secs": pb.position_secs,
        "is_paused": pb.is_paused,
        "loop_mode": pb.loop_mode.display_text(),
        "volume": pb.volume,
        "queue_len": pb.queue_len,
        "history_len": pb.history_len,
        "engine_state": pb.engine_state.display_text(),
        "voice_state": pb.voice_state.display_text(),
        "playback_generation": pb.playback_generation,
        "last_error": pb.last_error,
    }))
}

#[derive(Deserialize)]
struct ActionPayload {
    action: String,
    chat_id: Option<i64>,
    query: Option<String>,
}

async fn api_action_handler(
    State(app): State<Arc<AppState>>,
    Json(payload): Json<ActionPayload>,
) -> Json<serde_json::Value> {
    let chat_id = payload.chat_id.unwrap_or(0);
    match payload.action.as_str() {
        "pause" => { let _ = app.media_engine.pause(chat_id).await; }
        "resume" => { let _ = app.media_engine.resume(chat_id).await; }
        "skip" => { let _ = app.media_engine.skip(chat_id).await; }
        "stop" => { let _ = app.media_engine.stop(chat_id).await; }
        "play" => {
            if let Some(q) = payload.query.filter(|s| !s.trim().is_empty()) {
                let state_me = app.media_engine.clone();
                let ai_me = app.ai.clone();
                let lazy_providers = app.lazy_providers.clone();
                tokio::spawn(async move {
                    if let Ok(processed) = ai_me.process_query(&q).await {
                        let live_router = crate::commands::build_live_router(&lazy_providers, &lazy_providers.config);
                        if let Ok(t) = live_router.search(&processed, 0, "WebUser").await {
                            let _ = state_me.repo.enqueue(chat_id, t.clone()).await;
                            let _ = state_me.play(chat_id, &t).await;
                        }
                    }
                });
            }
        }
        _ => {}
    }
    Json(json!({"status": "ok"}))
}

pub struct AppState {
    pub config: Config,
    pub media_engine: Arc<MediaEngine>,
    pub ai: Arc<AiReceiver>,
    pub lazy_providers: Arc<LazyProviders>,
    pub db: Arc<MemoryFirstDbRepository>,
}

/// Lazy provider factory — providers are created on first use, not at startup.
/// This makes bot boot nearly instant on low-end hardware.
pub struct LazyProviders {
    config: Config,
    http_client: reqwest::Client,
    youtube: RwLock<Option<Arc<YouTubeResolver>>>,
    spotify: RwLock<Option<Arc<SpotifyResolver>>>,
    apple: RwLock<Option<Arc<AppleResolver>>>,
    soundcloud: RwLock<Option<Arc<SoundCloudResolver>>>,
    direct: Option<Arc<DirectResolver>>,
}

impl LazyProviders {
    pub fn new(config: Config, http_client: reqwest::Client) -> Self {
        Self {
            config: config.clone(),
            http_client,
            youtube: RwLock::new(None),
            spotify: RwLock::new(None),
            apple: RwLock::new(None),
            soundcloud: RwLock::new(None),
            direct: Some(Arc::new(DirectResolver::new(
                reqwest::Client::builder()
                    .timeout(Duration::from_secs(15))
                    .connect_timeout(Duration::from_secs(5))
                    .build()
                    .unwrap_or_else(|_| reqwest::Client::new()),
                &config,
            ))),
        }
    }

    fn youtube(&self) -> Arc<YouTubeResolver> {
        let mut lock = self.youtube.write().unwrap();
        lock.get_or_insert_with(|| {
            let cfg = &self.config;
            Arc::new(YouTubeResolver::new(
                self.http_client.clone(),
                if cfg.active_invidious_instances.is_empty() {
                    cfg.invidious_instances.clone()
                } else {
                    cfg.active_invidious_instances.clone()
                },
                if cfg.active_piped_instances.is_empty() {
                    cfg.piped_instances.clone()
                } else {
                    cfg.active_piped_instances.clone()
                },
                cfg.resolver_cache_ttl_secs,
                cfg.yt_dlp_enabled,
                cfg.yt_dlp_binary.clone(),
                Duration::from_secs(cfg.yt_dlp_timeout_secs),
            ))
        }).clone()
    }

    fn spotify(&self) -> Arc<SpotifyResolver> {
        let mut lock = self.spotify.write().unwrap();
        lock.get_or_insert_with(|| {
            Arc::new(SpotifyResolver::new(
                self.http_client.clone(),
                self.config.spotify_client_id.clone(),
                self.config.spotify_client_secret.clone(),
                Some(self.youtube()),
            ))
        }).clone()
    }

    fn apple(&self) -> Arc<AppleResolver> {
        let mut lock = self.apple.write().unwrap();
        lock.get_or_insert_with(|| {
            Arc::new(AppleResolver::new(self.http_client.clone(), Some(self.youtube())))
        }).clone()
    }

    fn soundcloud(&self) -> Arc<SoundCloudResolver> {
        let mut lock = self.soundcloud.write().unwrap();
        lock.get_or_insert_with(|| {
            Arc::new(SoundCloudResolver::new(
                self.http_client.clone(),
                self.config.soundcloud_client_id.clone(),
                Some(self.youtube()),
            ))
        }).clone()
    }

    pub fn get_route(&self, platform: Platform) -> Option<Route> {
        let youtube = self.youtube();
        let spotify = self.spotify();
        let apple = self.apple();
        let soundcloud = self.soundcloud();
        match platform {
            Platform::DirectUrl => self.direct.as_ref().map(|d| Route::new(platform, d.clone())),
            Platform::YouTube => Some(Route::new(platform, youtube)),
            Platform::Spotify =>
                if self.config.spotify_client_id.is_some() && self.config.spotify_client_secret.is_some() {
                    Some(Route::new(platform, spotify))
                } else {
                    None
                },
            Platform::AppleMusic => Some(Route::new(platform, apple)),
            Platform::SoundCloud =>
                if self.config.soundcloud_client_id.is_some() {
                    Some(Route::new(platform, soundcloud))
                } else {
                    None
                },
        }
    }

    pub fn get_search_adapter(&self, platform: Platform) -> Option<Arc<dyn SourceAdapter>> {
        match platform {
            Platform::YouTube => Some(self.youtube()),
            Platform::Spotify => {
                if self.config.spotify_client_id.is_some() && self.config.spotify_client_secret.is_some() {
                    Some(self.spotify())
                } else {
                    None
                }
            }
            Platform::AppleMusic => Some(self.apple()),
            Platform::SoundCloud => {
                if self.config.soundcloud_client_id.is_some() {
                    Some(self.soundcloud())
                } else {
                    None
                }
            }
            Platform::DirectUrl => None,
        }
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    eprintln!("[BOOT] main() entered");
    init_logger();
    tracing::info!("☠️ Initializing Brook Music Bot (Rust Modular Engine v0.2.0)");
    eprintln!("[BOOT] logger initialized");

    let config = Config::load().await;
    eprintln!("[BOOT] config loaded");
    let db_repo = Arc::new(MemoryFirstDbRepository::new(config.database_url.clone()));
    db_repo.log_analytics("bot_startup", "Heroku dyno initialized").await?;
    eprintln!("[BOOT] db repo initialized");

    let http_client = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .connect_timeout(Duration::from_secs(5))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new());

    // 3. Build a minimal router shell now, resolve real providers lazily on first use.
    let lazy = Arc::new(LazyProviders::new(config.clone(), http_client));
    let router = Arc::new(MusicRouter::new(vec![], vec![], &config));
    let _url_resolver = Arc::new(UrlResolver::new(router.clone()));
    let _video_resolver = Arc::new(VideoResolver::new(router.clone()));
    let ai = Arc::new(AiReceiver::new(&config));

    // 4. Media Engine — light queue repo, transport deferred until first playback.
    let queue_repo = Arc::new(InMemoryQueueRepository::new(config.max_queue_size, config.default_volume));
    let bot = config.bot_token.as_ref().map(|t| Bot::new(t.clone()));

    // Resolve voice transport eagerly — necessary for voice-chat playback.
    // Falls back to the inert TelegramAudioTransport only if MTProto auth fails.
    let live_router = Arc::new(crate::commands::build_live_router(&lazy, &config));
    let voice_transport: Option<Arc<VoiceChatTransport>> =
        connect_voice_transport(&config, bot.clone(), live_router.clone())
            .await
            .map(Arc::new);

    let transport: Arc<dyn PlaybackTransport> = match &voice_transport {
        Some(vt) => vt.clone(),
        None => Arc::new(TelegramAudioTransport::new(config.bot_token.as_ref().map(|t| Bot::new(t.clone())))),
    };

    let media_engine = Arc::new(MediaEngine::new(queue_repo, transport));
    eprintln!("[BOOT] media engine created");

    let state = Arc::new(AppState {
        config: config.clone(),
        media_engine,
        ai,
        lazy_providers: lazy,
        db: db_repo.clone(),
    });

    eprintln!("[BOOT] state created, setting up HTTP server on port {}", config.port.unwrap_or(8000));
    // 5. Axum HTTP Server & Web UI — starts immediately, no heavy init blocking.
    let port = config.port.unwrap_or(8000);
    let app_state_api = state.clone();

    let app = Router::new()
        .route("/", get(index_handler))
        .route("/static/brook.png", get(brook_image_handler))
        .route("/health", get(|| async { Json(json!({"status": "healthy", "version": "v0.2.0"})) }))
        .route("/stream", get(stream_handler))
        .route("/api/state", get(api_state_handler))
        .route("/api/action", post(api_action_handler))
        .route("/stats", get(move || {
            let st = app_state_api.clone();
            async move {
                let chats = st.media_engine.repo.active_chats().len();
                Json(json!({
                    "status": "online",
                    "active_chats": chats,
                    "platforms": [&["direct"]]
                }))
            }
        }))
        .with_state(state.clone());

    tokio::spawn(async move {
        let addr = SocketAddr::from(([0, 0, 0, 0], port));
        let listener = match tokio::net::TcpListener::bind(addr).await {
            Ok(l) => l,
            Err(e) => {
                tracing::error!(port, error = %e, "Failed to bind HTTP listener");
                return;
            }
        };
        tracing::info!(port, "Soul King Brook Web UI live at http://0.0.0.0:{port}");
        if let Err(e) = axum::serve(listener, app).await {
            tracing::error!(error = %e, "Axum HTTP server error");
        }
    });

    eprintln!("[BOOT] HTTP server spawned, setting up Telegram dispatcher...");
    // 6. Background In-Group Telegram Progress Ticker
    if let Some(bot_ticker) = bot.clone() {
        let me_ticker = state.media_engine.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(5));
            loop {
                interval.tick().await;
                let active_chats = me_ticker.repo.active_chats();
                for chat_id in active_chats {
                    if let Ok(st) = me_ticker.state(chat_id).await {
                        if let (Some(msg_id), Some(curr)) = (st.player_message_id, &st.current) {
                            if !st.is_paused && st.engine_state == crate::media_engine::EngineState::Playing {
                                let text = crate::commands::SoulKingUI::format_now_playing(
                                    curr,
                                    st.position_secs,
                                    st.is_paused,
                                    &st.loop_mode,
                                    st.voice_state,
                                    &st.queue,
                                );
                                let keyboard = crate::commands::SoulKingUI::now_playing_keyboard(st.is_paused);
                                let _ = bot_ticker
                                    .edit_message_text(teloxide::types::ChatId(chat_id), teloxide::types::MessageId(msg_id), text)
                                    .parse_mode(teloxide::types::ParseMode::Html)
                                    .reply_markup(keyboard)
                                    .await;
                            }
                        }
                    }
                }
            }
        });
    }

    eprintln!("[BOOT] entering dispatcher loop");
    // 7. Teloxide Dispatcher
    if let Some(bot) = bot {
        let ai = state.ai.clone();
        let media_engine = state.media_engine.clone();
        let media_engine_cb = state.media_engine.clone();
        let lazy_providers = state.lazy_providers.clone();

        let handler = dptree::entry()
            .branch(
                Update::filter_message().filter_command::<BotCommand>().endpoint(
                    move |bot: Bot, msg: Message, cmd: BotCommand| {
                        let ai = ai.clone();
                        let media_engine = media_engine.clone();
                        let lazy_providers = lazy_providers.clone();
                        async move {
                            handle_command(bot, msg, cmd, ai, media_engine, lazy_providers).await
                        }
                    },
                )
            )
            .branch(
                Update::filter_callback_query().endpoint(
                    move |bot: Bot, q: teloxide::types::CallbackQuery| {
                        let media_engine = media_engine_cb.clone();
                        async move {
                            crate::commands::handle_callback_query(bot, q, media_engine).await
                        }
                    },
                )
            )
            .branch(
                Update::filter_message().endpoint(|_bot: Bot, _msg: Message| async move {
                    Ok::<(), anyhow::Error>(())
                })
            );

        let mut dispatcher = Dispatcher::builder(bot, handler).build();
        tokio::select! {
            _ = dispatcher.dispatch() => {},
            _ = tokio::signal::ctrl_c() => {
                tracing::info!("Received shutdown signal, cleaning up streams...");
                if let Some(vt) = &voice_transport {
                    vt.shutdown_all().await;
                }
            }
        }
    } else {
        // No BOT_TOKEN configured yet: still keep the HTTP control plane alive so
        // the dyno doesn't exit (R10) on first deploy before config vars are set.
        // Heroku restarts the dyno automatically once BOT_TOKEN is added.
        tracing::info!(
            "BOT_TOKEN not configured. HTTP UI is up on :{port}; add BOT_TOKEN (+ friends) as config vars and the Telegram dispatcher will start on next release.",
        );
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                tracing::info!("Received shutdown signal, cleaning up streams...");
                if let Some(vt) = &voice_transport {
                    vt.shutdown_all().await;
                }
            }
        }
    }

    Ok(())
}