use std::process::Stdio;
use tokio::process::{Child, Command};
use tracing::info;
use crate::error::{BotError, Result};

pub struct FFmpegAudioPipeline;

impl FFmpegAudioPipeline {
    pub fn spawn_pcm_stream(
        input_url: &str,
        seek_secs: Option<u64>,
        volume: u32,
        effect_filters: Option<&str>,
    ) -> Result<Child> {
        let mut cmd = Command::new("ffmpeg");
        cmd.arg("-hide_banner")
            .arg("-loglevel")
            .arg("error");

        if let Some(ss) = seek_secs {
            cmd.arg("-ss").arg(ss.to_string());
        }

        cmd.arg("-i").arg(input_url);

        // Build audio filter chain
        let mut filters = vec![format!("volume={:.2}", volume as f64 / 100.0)];
        if let Some(eff) = effect_filters {
            if !eff.is_empty() {
                filters.push(eff.to_string());
            }
        }
        let filter_str = filters.join(",");

        cmd.arg("-af")
            .arg(filter_str)
            .arg("-f")
            .arg("s16le")
            .arg("-ar")
            .arg("48000")
            .arg("-ac")
            .arg("2")
            .arg("pipe:1")
            .stdout(Stdio::piped())
            .stderr(Stdio::null());

        info!("Spawning FFmpeg stream for input: {}", input_url);

        let child = cmd.spawn().map_err(|e| BotError::Audio(format!("Failed to spawn FFmpeg: {}", e)))?;
        Ok(child)
    }
}
