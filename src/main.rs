mod api;
mod audio;
mod cache;
mod commands;
mod config;
mod core;
mod db;
mod error;
mod logger;
mod ui;

#[cfg(test)]
mod tests;

use std::sync::Arc;
use teloxide::prelude::*;
use tracing::{error, info};

use crate::{
    cache::AppCache,
    commands::{handle_command, AppState, Command},
    config::Config,
    core::{call_manager::CallManager, music_backend::MusicBackend, queue::QueueManager},
    db::Database,
    logger::init_logger,
};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_logger();
    info!("☠️ Initializing Brook Music Bot (Rust Engine v0.1.0)...");

    let config = Config::load();
    let db = Database::connect(&config.sqlite_db_path).await?;
    let cache = AppCache::new();
    let queues = QueueManager::new();
    let calls = CallManager::new();
    let music_backend = MusicBackend::new(&config);

    let port = config.port;

    let app_state = Arc::new(AppState {
        config: config.clone(),
        db,
        cache,
        queues,
        calls,
        music_backend,
    });

    // Start Axum REST API server if PORT is configured
    if let Some(p) = port {
        let state_clone = app_state.clone();
        tokio::spawn(async move {
            api::start_api_server(p, state_clone).await;
        });
    }

    // Start Teloxide Telegram Bot Listener
    if let Some(token) = &config.bot_token {
        info!("Starting Teloxide Telegram Bot Listener...");
        let bot = Bot::new(token);

        let handler = dptree::entry().branch(
            Update::filter_message()
                .filter_command::<Command>()
                .endpoint(handle_command),
        );

        Dispatcher::builder(bot, handler)
            .dependencies(dptree::deps![app_state])
            .build()
            .dispatch()
            .await;
    } else {
        error!("BOT_TOKEN is missing! Bot listener skipped. Axum HTTP server will remain running.");
        // Keep main alive if HTTP server is running
        tokio::signal::ctrl_c().await?;
    }

    Ok(())
}
