use std::sync::Arc;
use dashmap::DashMap;
use tokio::process::Child;
use tokio::sync::RwLock;
use tracing::{info, error};

use crate::audio::ffmpeg::FFmpegAudioPipeline;
use crate::core::queue::Track;
use crate::error::{BotError, Result};

pub struct ActiveVoiceCall {
    pub chat_id: i64,
    pub current_track: Option<Track>,
    pub ffmpeg_process: Option<Child>,
    pub is_playing: bool,
    pub volume: u32,
}

impl ActiveVoiceCall {
    pub fn new(chat_id: i64) -> Self {
        Self {
            chat_id,
            current_track: None,
            ffmpeg_process: None,
            is_playing: false,
            volume: 100,
        }
    }

    pub fn stop(&mut self) {
        if let Some(mut child) = self.ffmpeg_process.take() {
            let _ = child.start_kill();
        }
        self.is_playing = false;
        self.current_track = None;
    }
}

#[derive(Clone, Default)]
pub struct CallManager {
    calls: Arc<DashMap<i64, Arc<RwLock<ActiveVoiceCall>>>>,
}

impl CallManager {
    pub fn new() -> Self {
        Self {
            calls: Arc::new(DashMap::new()),
        }
    }

    pub async fn start_stream(
        &self,
        chat_id: i64,
        track: Track,
        volume: u32,
        seek_secs: Option<u64>,
    ) -> Result<()> {
        let call_entry = self
            .calls
            .entry(chat_id)
            .or_insert_with(|| Arc::new(RwLock::new(ActiveVoiceCall::new(chat_id))))
            .value()
            .clone();

        let mut call = call_entry.write().await;
        call.stop();

        match FFmpegAudioPipeline::spawn_pcm_stream(&track.url, seek_secs, volume, None) {
            Ok(child) => {
                call.ffmpeg_process = Some(child);
                call.current_track = Some(track.clone());
                call.is_playing = true;
                call.volume = volume;
                info!("Pure Rust Voice Stream started for chat_id {} (track: {})", chat_id, track.title);
                Ok(())
            }
            Err(e) => {
                error!("Failed to start voice stream for chat_id {}: {}", chat_id, e);
                Err(e)
            }
        }
    }

    pub async fn stop_stream(&self, chat_id: i64) {
        if let Some((_, call_lock)) = self.calls.remove(&chat_id) {
            let mut call = call_lock.write().await;
            call.stop();
            info!("Pure Rust Voice Stream stopped for chat_id {}", chat_id);
        }
    }

    pub fn is_active(&self, chat_id: i64) -> bool {
        self.calls.contains_key(&chat_id)
    }
}
