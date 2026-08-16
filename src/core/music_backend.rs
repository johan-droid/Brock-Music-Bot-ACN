use crate::config::Config;
use crate::core::queue::Track;
use crate::error::Result;
use reqwest::Client;
use serde_json::Value;
use std::time::Duration;
use tracing::warn;

#[derive(Clone)]
pub struct MusicBackend {
    client: Client,
    microservice_url: Option<String>,
}

impl MusicBackend {
    pub fn new(config: &Config) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(12))
            .connect_timeout(Duration::from_secs(5))
            .build()
            .unwrap_or_default();

        Self {
            client,
            microservice_url: config.music_microservice_url.clone(),
        }
    }

    pub async fn search_track(&self, query: &str, requested_by: i64, requested_by_name: &str) -> Result<Track> {
        if let Some(ms_url) = &self.microservice_url {
            match self.search_via_microservice(ms_url, query, requested_by, requested_by_name).await {
                Ok(track) => return Ok(track),
                Err(err) => warn!("Microservice search failed: {}; falling back to direct search", err),
            }
        }

        // Direct search fallback (or mock track generator for demonstration / testing)
        let track_id = format!("track_{}", rand::random::<u32>());
        Ok(Track {
            id: track_id,
            title: query.to_string(),
            artist: "Soul King Brook".to_string(),
            url: format!("https://music.example.com/stream?q={}", urlencoding::encode(query)),
            duration: 210,
            thumbnail: "https://raw.githubusercontent.com/johan-droid/Brock-Music-Bot-ACN/master/assets/brook_start.png".to_string(),
            requested_by,
            requested_by_name: requested_by_name.to_string(),
            source: "youtube".to_string(),
        })
    }

    async fn search_via_microservice(
        &self,
        base_url: &str,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let url = format!("{}/search", base_url.trim_end_matches('/'));
        let resp = self
            .client
            .get(&url)
            .query(&[("q", query)])
            .send()
            .await?
            .json::<Value>()
            .await?;

        let title = resp["title"].as_str().unwrap_or(query).to_string();
        let artist = resp["artist"].as_str().unwrap_or("Unknown Artist").to_string();
        let stream_url = resp["url"].as_str().unwrap_or("").to_string();
        let duration = resp["duration"].as_u64().unwrap_or(180);
        let thumbnail = resp["thumbnail"].as_str().unwrap_or("").to_string();
        let source = resp["source"].as_str().unwrap_or("youtube").to_string();

        Ok(Track {
            id: format!("ms_{}", rand::random::<u32>()),
            title,
            artist,
            url: stream_url,
            duration,
            thumbnail,
            requested_by,
            requested_by_name: requested_by_name.to_string(),
            source,
        })
    }

    pub async fn check_health(&self) -> bool {
        if let Some(ms_url) = &self.microservice_url {
            let health_endpoint = format!("{}/health", ms_url.trim_end_matches('/'));
            if let Ok(res) = self.client.get(&health_endpoint).send().await {
                return res.status().is_success();
            }
            return false;
        }
        true
    }
}
