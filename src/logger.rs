use tracing_subscriber::{fmt, EnvFilter};

pub fn init_logger() {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,brook_music_bot=debug"));

    fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_thread_ids(true)
        .compact()
        .init();
}
