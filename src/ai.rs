use serde_json::{json, Value};
use std::time::Duration;
use tracing::debug;

use crate::config::Config;
use crate::error::Result;

/// Intelligence Layer 1: Receiver
///
/// Interprets the human — handles query intent understanding, title completion,
/// and normalization using NVIDIA NIM AI inference microservices when configured,
/// with automatic local fallback.
pub struct AiReceiver {
    client: reqwest::Client,
    nvidia_api_key: Option<String>,
    nvidia_base_url: String,
    nvidia_model: String,
}

impl AiReceiver {
    pub fn new(config: &Config) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .unwrap_or_else(|_| reqwest::Client::new());

        Self {
            client,
            nvidia_api_key: config.nvidia_nim_api_key.clone(),
            nvidia_base_url: config.nvidia_nim_base_url.clone(),
            nvidia_model: config.nvidia_nim_model.clone(),
        }
    }

    /// Understand, complete, and normalize a user title query for the Music Router.
    pub async fn process_query(&self, raw_query: &str) -> Result<String> {
        let trimmed = raw_query.trim();

        if let Some(nim_result) = self.infer_nvidia_nim(trimmed).await {
            debug!(
                raw = raw_query,
                nim_processed = %nim_result,
                model = %self.nvidia_model,
                "NVIDIA NIM AI Receiver processed query"
            );
            return Ok(nim_result);
        }

        // Local fallback normalization & intent completion
        let normalized = self.normalize_title(trimmed);
        let completed = self.complete_title_intent(&normalized);

        debug!(
            raw = raw_query,
            processed = %completed,
            "Local AI Receiver processed title query"
        );

        Ok(completed)
    }

    /// Call NVIDIA NIM OpenAI-compatible API endpoint to interpret human search intent.
    async fn infer_nvidia_nim(&self, raw_query: &str) -> Option<String> {
        let api_key = self.nvidia_api_key.as_ref()?;
        let endpoint = format!(
            "{}/chat/completions",
            self.nvidia_base_url.trim_end_matches('/')
        );

        let body = json!({
            "model": self.nvidia_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a music title normalization assistant. Extract and return ONLY the clean song title and artist name without quotes, punctuation, or commentary."
                },
                {
                    "role": "user",
                    "content": raw_query
                }
            ],
            "temperature": 0.1,
            "max_tokens": 60
        });

        let resp = self
            .client
            .post(&endpoint)
            .header("Authorization", format!("Bearer {api_key}"))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .ok()?;

        if !resp.status().is_success() {
            debug!(status = %resp.status(), "NVIDIA NIM API request non-200; falling back to local receiver");
            return None;
        }

        let json: Value = resp.json().await.ok()?;
        let content = json
            .pointer("/choices/0/message/content")
            .and_then(|c| c.as_str())?
            .trim()
            .to_string();

        if content.is_empty() {
            None
        } else {
            Some(content)
        }
    }

    fn normalize_title(&self, input: &str) -> String {
        input.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    fn complete_title_intent(&self, input: &str) -> String {
        let mut cleaned = input.to_string();
        for noise in &[
            "(Official Video)",
            "[Official Video]",
            "(Official Audio)",
            "[Official Audio]",
            "(Lyric Video)",
        ] {
            if cleaned.to_lowercase().contains(&noise.to_lowercase()) {
                cleaned = cleaned.replace(noise, "");
            }
        }
        cleaned.trim().to_string()
    }
}
