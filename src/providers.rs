use std::net::IpAddr;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use dashmap::DashMap;
use serde_json::{json, Value};
use tokio::time::sleep;
use tracing::{debug, warn};
use url::Url;

use crate::config::Config;
use crate::error::{BotError, Result};
use crate::router::{Platform, ResolvedAudio, SourceAdapter, SourceKind, Track, TrackId};

// --- Exponential Backoff Helper ---

#[derive(Debug, Clone, Copy)]
pub struct BackoffConfig {
    pub base_delay: Duration,
    pub max_delay: Duration,
    pub multiplier: f64,
    pub max_retries: u32,
    pub jitter_factor: f64,
}

impl Default for BackoffConfig {
    fn default() -> Self {
        Self {
            base_delay: Duration::from_millis(500),
            max_delay: Duration::from_secs(30),
            multiplier: 2.0,
            max_retries: 3,
            jitter_factor: 0.1,
        }
    }
}

pub async fn retry_with_backoff<T, E, F, Fut>(
    mut operation: F,
    should_retry: impl Fn(&E) -> bool,
    config: BackoffConfig,
) -> std::result::Result<T, E>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = std::result::Result<T, E>>,
    E: std::fmt::Display,
{
    let mut delay = config.base_delay;
    let mut attempt = 0;

    loop {
        match operation().await {
            Ok(value) => return Ok(value),
            Err(err) if attempt < config.max_retries && should_retry(&err) => {
                let jitter = delay.as_secs_f64()
                    * config.jitter_factor
                    * (rand::random::<f64>() * 2.0 - 1.0);
                let delay_with_jitter = delay + Duration::from_secs_f64(jitter.max(0.0));
                warn!(
                    attempt = attempt + 1,
                    max_retries = config.max_retries,
                    delay_ms = delay_with_jitter.as_millis(),
                    error = %err,
                    "Operation failed, retrying with backoff"
                );
                sleep(delay_with_jitter).await;
                delay = Duration::from_secs_f64(
                    (delay.as_secs_f64() * config.multiplier).min(config.max_delay.as_secs_f64()),
                );
                attempt += 1;
            }
            Err(err) => {
                debug!(attempt = attempt + 1, error = %err, "Operation failed, no more retries");
                return Err(err);
            }
        }
    }
}

pub fn is_retryable_reqwest_error(err: &reqwest::Error) -> bool {
    err.is_timeout()
        || err.is_connect()
        || err.is_request()
        || err
            .status()
            .map(|s| s.is_server_error() || s.as_u16() == 429)
            .unwrap_or(false)
}

// --- YouTube Resolver (InnerTube + yt-dlp) ---

struct YtSearchHit {
    video_id: String,
    title: String,
    artist: Option<String>,
    duration_secs: u64,
    thumbnail_url: Option<String>,
}

#[allow(dead_code)]
#[derive(Clone)]
pub struct YouTubeResolver {
    client: reqwest::Client,
    _invidious: Vec<String>,
    _piped: Vec<String>,
    _cache_ttl: u64,
    search_cache: Arc<DashMap<String, (Instant, Track)>>,
    yt_dlp_enabled: bool,
    yt_dlp_binary: String,
    yt_dlp_timeout: Duration,
}

#[allow(dead_code)]
impl YouTubeResolver {
    const INNERTUBE_USER_AGENT: &'static str =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

    pub fn new(
        client: reqwest::Client,
        invidious_instances: Vec<String>,
        piped_instances: Vec<String>,
        cache_ttl: u64,
        yt_dlp_enabled: bool,
        yt_dlp_binary: String,
        yt_dlp_timeout: Duration,
    ) -> Self {
        Self {
            client,
            _invidious: invidious_instances,
            _piped: piped_instances,
            _cache_ttl: cache_ttl,
            search_cache: Arc::new(DashMap::new()),
            yt_dlp_enabled,
            yt_dlp_binary,
            yt_dlp_timeout,
        }
    }

    pub async fn search_track(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        <Self as SourceAdapter>::search(self, query, requested_by, requested_by_name).await
    }

    fn extract_video_id(url: &str) -> Option<String> {
        let lower = url.to_lowercase();
        let on_youtube_host = lower.starts_with("https://www.youtube.com/")
            || lower.starts_with("https://youtube.com/")
            || lower.starts_with("https://music.youtube.com/")
            || lower.starts_with("https://m.youtube.com/")
            || lower.starts_with("https://youtu.be/");
        if !on_youtube_host {
            return None;
        }
        if let Some(pos) = lower.find("youtu.be/") {
            let rest = &url[pos + 9..];
            let id = rest.split(['?', '/', '#']).next().unwrap_or("");
            if !id.trim().is_empty() {
                return Some(id.trim().to_string());
            }
        }
        if let Some((_, qs)) = url.split_once('?') {
            let qs = qs.split('#').next().unwrap_or(qs);
            for pair in qs.split('&') {
                if let Some((k, v)) = pair.split_once('=') {
                    if k.trim().eq_ignore_ascii_case("v") && !v.trim().is_empty() {
                        return Some(v.trim().to_string());
                    }
                }
            }
        }
        if let Some(pos) = lower.find("/shorts/") {
            let rest = &url[pos + 8..];
            let id = rest.split(['?', '/', '#']).next().unwrap_or("");
            if !id.trim().is_empty() {
                return Some(id.trim().to_string());
            }
        }
        None
    }

    fn innertube_body(context_extra: Value) -> Value {
        let mut body = json!({
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20231201.00.00",
                    "hl": "en",
                    "gl": "US"
                }
            }
        });
        if let (Some(obj), Some(extra)) = (body.as_object_mut(), context_extra.as_object()) {
            for (k, v) in extra {
                obj.insert(k.clone(), v.clone());
            }
        }
        body
    }

    async fn innertube_post(&self, endpoint: &str, body: Value) -> Option<Value> {
        let api_key = std::env::var("INNERTUBE_API_KEY")
            .or_else(|_| std::env::var("YOUTUBE_API_KEY"))
            .unwrap_or_default();
        let url = format!(
            "https://www.youtube.com/youtubei/v1/{endpoint}?prettyPrint=false&key={api_key}"
        );
        let resp = self
            .client
            .post(&url)
            .header("User-Agent", Self::INNERTUBE_USER_AGENT)
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body.to_string())
            .timeout(Duration::from_secs(6))
            .send()
            .await
            .ok()?;
        if resp.status().is_success() {
            resp.json::<Value>().await.ok()
        } else {
            None
        }
    }

    async fn innertube_search(&self, query: &str) -> Option<YtSearchHit> {
        let body = Self::innertube_body(json!({ "query": query }));
        let data = self.innertube_post("search", body).await?;
        Self::parse_innertube_search(&data)
    }

    fn extract_stream_url_from_player_json(data: &Value) -> Option<String> {
        let streaming_data = data.get("streamingData")?;

        // 1. Search adaptiveFormats first (best audio quality)
        if let Some(formats) = streaming_data
            .get("adaptiveFormats")
            .and_then(|v| v.as_array())
        {
            for f in formats {
                let ty = f.get("mimeType").and_then(|v| v.as_str()).unwrap_or("");
                if ty.starts_with("audio/") {
                    if let Some(url) = f.get("url").and_then(|v| v.as_str()) {
                        if !url.is_empty() && url.starts_with("http") {
                            return Some(url.to_string());
                        }
                    }
                }
            }
        }

        // 2. Search combined formats fallback
        if let Some(formats) = streaming_data.get("formats").and_then(|v| v.as_array()) {
            for f in formats {
                if let Some(url) = f.get("url").and_then(|v| v.as_str()) {
                    if !url.is_empty() && url.starts_with("http") {
                        return Some(url.to_string());
                    }
                }
            }
        }

        None
    }

    async fn innertube_resolve(&self, video_id: &str) -> Option<String> {
        // 1. Android Client Payload (Fastest & Most Reliable Direct Audio Streams)
        let android_body = json!({
            "context": {
                "client": {
                    "clientName": "ANDROID",
                    "clientVersion": "19.05.36",
                    "androidSdkVersion": 30,
                    "hl": "en",
                    "gl": "US"
                }
            },
            "videoId": video_id
        });

        if let Some(data) = self.innertube_post("player", android_body).await {
            if let Some(url) = Self::extract_stream_url_from_player_json(&data) {
                return Some(url);
            }
        }

        // 2. TVHTML5 Embedded Player Payload (Secondary Ultra-Fast Fallback)
        let tv_body = json!({
            "context": {
                "client": {
                    "clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
                    "clientVersion": "2.0",
                    "hl": "en",
                    "gl": "US"
                }
            },
            "videoId": video_id
        });

        if let Some(data) = self.innertube_post("player", tv_body).await {
            if let Some(url) = Self::extract_stream_url_from_player_json(&data) {
                return Some(url);
            }
        }

        // 3. Web Client Payload
        let web_body = Self::innertube_body(json!({ "videoId": video_id }));
        if let Some(data) = self.innertube_post("player", web_body).await {
            if let Some(url) = Self::extract_stream_url_from_player_json(&data) {
                return Some(url);
            }
        }

        None
    }

    async fn ytdlp_resolve(&self, video_id: &str) -> Option<String> {
        if !self.yt_dlp_enabled {
            return None;
        }
        use tokio::process::Command;
        let url = format!("https://www.youtube.com/watch?v={video_id}");
        let output = tokio::time::timeout(
            self.yt_dlp_timeout,
            Command::new(&self.yt_dlp_binary)
                .args([
                    "--no-warnings",
                    "--no-playlist",
                    "--format",
                    "bestaudio[ext=m4a]/bestaudio",
                    "--get-url",
                    &url,
                ])
                .output(),
        )
        .await
        .ok()?
        .ok()?;

        if !output.status.success() {
            return None;
        }
        let first = String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(|s| s.trim().to_string())
            .find(|s| s.starts_with("https://"))?;
        Some(first)
    }

    fn parse_innertube_search(json: &Value) -> Option<YtSearchHit> {
        fn walk(value: &Value) -> Option<YtSearchHit> {
            if let Some(rend) = value.get("videoRenderer") {
                if let Some(hit) = parse_renderer(rend) {
                    return Some(hit);
                }
            }
            if let Some(obj) = value.as_object() {
                for v in obj.values() {
                    if let Some(hit) = walk(v) {
                        return Some(hit);
                    }
                }
            } else if let Some(arr) = value.as_array() {
                for v in arr {
                    if let Some(hit) = walk(v) {
                        return Some(hit);
                    }
                }
            }
            None
        }
        fn parse_renderer(rend: &Value) -> Option<YtSearchHit> {
            let video_id = rend
                .get("videoId")
                .and_then(|v| v.as_str())?
                .trim()
                .to_string();
            let title = rend
                .get("title")
                .and_then(|t| t.get("runs"))
                .and_then(|r| r.as_array())
                .and_then(|runs| runs.first())
                .and_then(|run| run.get("text"))
                .and_then(|txt| txt.as_str())?
                .to_string();

            let artist = rend
                .get("ownerText")
                .and_then(|t| t.get("runs"))
                .and_then(|r| r.as_array())
                .and_then(|runs| runs.first())
                .and_then(|run| run.get("text"))
                .and_then(|txt| txt.as_str())
                .map(|s| s.to_string());

            let duration_secs = rend
                .get("lengthText")
                .and_then(|t| t.get("simpleText"))
                .and_then(|s| s.as_str())
                .map(parse_duration)
                .unwrap_or(0);

            let thumbnail_url = rend
                .pointer("/thumbnail/thumbnails/0/url")
                .and_then(|u| u.as_str())
                .map(|s| s.to_string());

            Some(YtSearchHit {
                video_id,
                title,
                artist,
                duration_secs,
                thumbnail_url,
            })
        }

        walk(json)
    }
}

fn parse_duration(s: &str) -> u64 {
    let parts: Vec<&str> = s.split(':').collect();
    match parts.len() {
        3 => {
            let h: u64 = parts[0].parse().unwrap_or(0);
            let m: u64 = parts[1].parse().unwrap_or(0);
            let sec: u64 = parts[2].parse().unwrap_or(0);
            h * 3600 + m * 60 + sec
        }
        2 => {
            let m: u64 = parts[0].parse().unwrap_or(0);
            let sec: u64 = parts[1].parse().unwrap_or(0);
            m * 60 + sec
        }
        1 => parts[0].parse().unwrap_or(0),
        _ => 0,
    }
}

#[async_trait]
impl SourceAdapter for YouTubeResolver {
    fn name(&self) -> &'static str {
        "youtube"
    }

    fn platform(&self) -> Platform {
        Platform::YouTube
    }

    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let key = query.trim().to_lowercase();

        if let Some(video_id) = Self::extract_video_id(query) {
            return Ok(Track {
                id: TrackId::new(format!("yt:{video_id}")),
                title: format!("YouTube Track ({video_id})"),
                artist: None,
                url: format!("https://www.youtube.com/watch?v={video_id}"),
                duration_secs: 0,
                thumbnail_url: None,
                requested_by,
                requested_by_name: requested_by_name.to_string(),
                source: SourceKind::YouTube,
                external_id: Some(video_id),
            });
        }

        if let Some(hit) = self.innertube_search(query).await {
            let track = Track {
                id: TrackId::new(format!("yt:{}", hit.video_id)),
                title: hit.title,
                artist: hit.artist,
                url: format!("https://www.youtube.com/watch?v={}", hit.video_id),
                duration_secs: hit.duration_secs,
                thumbnail_url: hit.thumbnail_url,
                requested_by,
                requested_by_name: requested_by_name.to_string(),
                source: SourceKind::YouTube,
                external_id: Some(hit.video_id),
            };
            self.search_cache
                .insert(key, (Instant::now(), track.clone()));
            return Ok(track);
        }

        Err(BotError::NotFound(format!(
            "YouTube track not found for '{query}'"
        )))
    }

    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio> {
        let extracted = Self::extract_video_id(&track.url);
        let video_id = track
            .external_id
            .as_deref()
            .or(extracted.as_deref())
            .ok_or_else(|| BotError::NotFound("Track missing YouTube videoId".to_string()))?;

        // 1. Try Innertube direct audio URL
        if let Some(direct_url) = self.innertube_resolve(video_id).await {
            tracing::info!(video_id = %video_id, stream_url = %direct_url, "Resolved YouTube track to direct HTTPS Innertube audio URL");
            return Ok(ResolvedAudio {
                file_url: direct_url,
                headers: None,
                is_direct: true,
            });
        }

        // 2. Try yt-dlp direct audio URL
        if let Some(direct_url) = self.ytdlp_resolve(video_id).await {
            tracing::info!(video_id = %video_id, stream_url = %direct_url, "Resolved YouTube track to direct HTTPS yt-dlp audio URL");
            return Ok(ResolvedAudio {
                file_url: direct_url,
                headers: None,
                is_direct: true,
            });
        }

        // 3. Fallback to local /stream endpoint if available
        let port = std::env::var("PORT")
            .ok()
            .and_then(|p| p.parse::<u16>().ok())
            .unwrap_or(8000);
        let stream_url = format!("http://127.0.0.1:{port}/stream?yt={video_id}");

        tracing::warn!(video_id = %video_id, stream_url = %stream_url, "Direct resolution failed; falling back to local /stream endpoint");

        Ok(ResolvedAudio {
            file_url: stream_url,
            headers: None,
            is_direct: true,
        })
    }
}

// --- Spotify Resolver ---

#[derive(Clone)]
pub struct SpotifyResolver {
    client: reqwest::Client,
    client_id: Option<String>,
    client_secret: Option<String>,
    token_cache: Arc<Mutex<Option<(String, Instant)>>>,
    yt: Option<Arc<YouTubeResolver>>,
}

impl SpotifyResolver {
    const TOKEN_URL: &'static str = "https://accounts.spotify.com/api/token";
    const API_BASE: &'static str = "https://api.spotify.com/v1";

    pub fn new(
        client: reqwest::Client,
        client_id: Option<String>,
        client_secret: Option<String>,
        yt: Option<Arc<YouTubeResolver>>,
    ) -> Self {
        Self {
            client,
            client_id,
            client_secret,
            token_cache: Arc::new(Mutex::new(None)),
            yt,
        }
    }

    async fn ensure_token(&self) -> Result<String> {
        let (id, secret) = match (&self.client_id, &self.client_secret) {
            (Some(id), Some(sec)) if !id.is_empty() && !sec.is_empty() => (id, sec),
            _ => {
                return Err(BotError::PlatformConfig(
                    "Spotify credentials not configured".into(),
                ))
            }
        };

        if let Ok(guard) = self.token_cache.lock() {
            if let Some((tok, exp)) = guard.as_ref() {
                if *exp > Instant::now() + Duration::from_secs(60) {
                    return Ok(tok.clone());
                }
            }
        }

        let basic = STANDARD.encode(format!("{id}:{secret}"));
        let resp = self
            .client
            .post(Self::TOKEN_URL)
            .header(reqwest::header::AUTHORIZATION, format!("Basic {basic}"))
            .header(
                reqwest::header::CONTENT_TYPE,
                "application/x-www-form-urlencoded",
            )
            .body("grant_type=client_credentials")
            .send()
            .await?
            .error_for_status()?;

        let json: Value = resp.json().await?;
        let token = json
            .get("access_token")
            .and_then(|t| t.as_str())
            .ok_or_else(|| {
                BotError::Internal("Spotify token response missing access_token".into())
            })?
            .to_string();

        let expires_in = json
            .get("expires_in")
            .and_then(|e| e.as_u64())
            .unwrap_or(3600);
        let expires_at = Instant::now() + Duration::from_secs(expires_in);

        if let Ok(mut guard) = self.token_cache.lock() {
            *guard = Some((token.clone(), expires_at));
        }

        Ok(token)
    }
}

#[async_trait]
impl SourceAdapter for SpotifyResolver {
    fn name(&self) -> &'static str {
        "spotify"
    }

    fn platform(&self) -> Platform {
        Platform::Spotify
    }

    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let token = self.ensure_token().await?;
        let url = format!(
            "{}/search?q={}&type=track&limit=1",
            Self::API_BASE,
            urlencoding::encode(query)
        );
        let resp = self
            .client
            .get(&url)
            .header(reqwest::header::AUTHORIZATION, format!("Bearer {token}"))
            .send()
            .await?
            .error_for_status()?;

        let json: Value = resp.json().await?;
        let item = json
            .pointer("/tracks/items/0")
            .ok_or_else(|| BotError::NotFound(format!("Spotify: no track found for '{query}'")))?;

        let track_name = item
            .get("name")
            .and_then(|n| n.as_str())
            .unwrap_or("Unknown")
            .to_string();
        let artist_name = item
            .pointer("/artists/0/name")
            .and_then(|a| a.as_str())
            .map(|s| s.to_string());
        let duration_ms = item
            .get("duration_ms")
            .and_then(|d| d.as_u64())
            .unwrap_or(0);
        let track_id = item
            .get("id")
            .and_then(|i| i.as_str())
            .unwrap_or("")
            .to_string();

        Ok(Track {
            id: TrackId::new(format!("spotify:{track_id}")),
            title: track_name,
            artist: artist_name,
            url: format!("https://open.spotify.com/track/{track_id}"),
            duration_secs: duration_ms / 1000,
            thumbnail_url: item
                .pointer("/album/images/0/url")
                .and_then(|u| u.as_str())
                .map(|s| s.to_string()),
            requested_by,
            requested_by_name: requested_by_name.to_string(),
            source: SourceKind::Spotify,
            external_id: Some(track_id),
        })
    }

    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio> {
        let yt = self.yt.as_ref().ok_or_else(|| {
            BotError::Internal(
                "Spotify adapter requires YouTube fallback resolver for audio".into(),
            )
        })?;
        let query = match &track.artist {
            Some(artist) => format!("{} {}", track.title, artist),
            None => track.title.clone(),
        };
        let yt_track = yt
            .search_track(&query, track.requested_by, &track.requested_by_name)
            .await?;
        yt.resolve(&yt_track).await
    }
}

// --- Apple Music Resolver ---

#[derive(Clone)]
pub struct AppleResolver {
    client: reqwest::Client,
    yt: Option<Arc<YouTubeResolver>>,
}

impl AppleResolver {
    pub fn new(client: reqwest::Client, yt: Option<Arc<YouTubeResolver>>) -> Self {
        Self { client, yt }
    }
}

#[async_trait]
impl SourceAdapter for AppleResolver {
    fn name(&self) -> &'static str {
        "apple"
    }

    fn platform(&self) -> Platform {
        Platform::AppleMusic
    }

    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let url = format!(
            "https://itunes.apple.com/search?term={}&entity=song&limit=1",
            urlencoding::encode(query)
        );
        let resp = self.client.get(&url).send().await?.error_for_status()?;
        let json: Value = resp.json().await?;
        let item = json.pointer("/results/0").ok_or_else(|| {
            BotError::NotFound(format!("Apple Music: no song found for '{query}'"))
        })?;

        let track_name = item
            .get("trackName")
            .and_then(|n| n.as_str())
            .unwrap_or("Unknown")
            .to_string();
        let artist_name = item
            .get("artistName")
            .and_then(|a| a.as_str())
            .map(|s| s.to_string());
        let duration_ms = item
            .get("trackTimeMillis")
            .and_then(|d| d.as_u64())
            .unwrap_or(0);
        let track_id = item
            .get("trackId")
            .and_then(|i| i.as_u64())
            .map(|i| i.to_string())
            .unwrap_or_default();

        Ok(Track {
            id: TrackId::new(format!("apple:{track_id}")),
            title: track_name,
            artist: artist_name,
            url: format!("https://music.apple.com/us/song/{track_id}"),
            duration_secs: duration_ms / 1000,
            thumbnail_url: item
                .get("artworkUrl100")
                .and_then(|u| u.as_str())
                .map(|s| s.to_string()),
            requested_by,
            requested_by_name: requested_by_name.to_string(),
            source: SourceKind::AppleMusic,
            external_id: Some(track_id),
        })
    }

    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio> {
        let yt = self.yt.as_ref().ok_or_else(|| {
            BotError::Internal(
                "Apple Music adapter requires YouTube fallback resolver for audio".into(),
            )
        })?;
        let query = match &track.artist {
            Some(artist) => format!("{} {}", track.title, artist),
            None => track.title.clone(),
        };
        let yt_track = yt
            .search_track(&query, track.requested_by, &track.requested_by_name)
            .await?;
        yt.resolve(&yt_track).await
    }
}

// --- SoundCloud Resolver ---

#[derive(Clone)]
pub struct SoundCloudResolver {
    client: reqwest::Client,
    client_id: Option<String>,
    yt: Option<Arc<YouTubeResolver>>,
}

impl SoundCloudResolver {
    pub fn new(
        client: reqwest::Client,
        client_id: Option<String>,
        yt: Option<Arc<YouTubeResolver>>,
    ) -> Self {
        Self {
            client,
            client_id,
            yt,
        }
    }
}

#[async_trait]
impl SourceAdapter for SoundCloudResolver {
    fn name(&self) -> &'static str {
        "soundcloud"
    }

    fn platform(&self) -> Platform {
        Platform::SoundCloud
    }

    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let client_id = self.client_id.as_deref().ok_or_else(|| {
            BotError::PlatformConfig("SOUNDCLOUD_CLIENT_ID not configured".into())
        })?;

        let url = format!(
            "https://api-v2.soundcloud.com/search/tracks?q={}&client_id={}&limit=1",
            urlencoding::encode(query),
            client_id
        );
        let resp = self.client.get(&url).send().await?.error_for_status()?;
        let json: Value = resp.json().await?;
        let item = json.pointer("/collection/0").ok_or_else(|| {
            BotError::NotFound(format!("SoundCloud: no track found for '{query}'"))
        })?;

        let track_id = item
            .get("id")
            .and_then(|i| i.as_u64())
            .map(|i| i.to_string())
            .unwrap_or_default();
        let title = item
            .get("title")
            .and_then(|t| t.as_str())
            .unwrap_or("Unknown")
            .to_string();
        let artist = item
            .pointer("/user/username")
            .and_then(|u| u.as_str())
            .map(|s| s.to_string());
        let duration_ms = item.get("duration").and_then(|d| d.as_u64()).unwrap_or(0);

        Ok(Track {
            id: TrackId::new(format!("sc:{track_id}")),
            title,
            artist,
            url: item
                .get("permalink_url")
                .and_then(|u| u.as_str())
                .unwrap_or("")
                .to_string(),
            duration_secs: duration_ms / 1000,
            thumbnail_url: item
                .get("artwork_url")
                .and_then(|u| u.as_str())
                .map(|s| s.to_string()),
            requested_by,
            requested_by_name: requested_by_name.to_string(),
            source: SourceKind::SoundCloud,
            external_id: Some(track_id),
        })
    }

    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio> {
        if let Some(yt) = &self.yt {
            let query = match &track.artist {
                Some(artist) => format!("{} {}", track.title, artist),
                None => track.title.clone(),
            };
            if let Ok(yt_track) = yt
                .search_track(&query, track.requested_by, &track.requested_by_name)
                .await
            {
                if let Ok(audio) = yt.resolve(&yt_track).await {
                    return Ok(audio);
                }
            }
        }
        Err(BotError::NotFound(
            "SoundCloud stream resolution unavailable".into(),
        ))
    }
}

// --- Direct Audio Link Resolver ---

fn is_blocked_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || v4.is_unspecified()
                || v4.is_broadcast()
                || v4.is_documentation()
                || v4.octets()[0] == 0
                || (v4.octets()[0] == 100 && (64..128).contains(&v4.octets()[1]))
        }
        IpAddr::V6(v6) => match v6.to_ipv4_mapped() {
            Some(v4) => is_blocked_ip(IpAddr::V4(v4)),
            None => {
                v6.is_loopback()
                    || v6.is_unspecified()
                    || (v6.segments()[0] & 0xfe00) == 0xfc00
                    || (v6.segments()[0] & 0xffc0) == 0xfe80
            }
        },
    }
}

#[derive(Clone)]
pub struct DirectResolver {
    client: reqwest::Client,
    max_size_bytes: u64,
    allowed_hosts: Vec<String>,
}

impl DirectResolver {
    pub fn new(client: reqwest::Client, config: &Config) -> Self {
        Self {
            client,
            max_size_bytes: config.max_direct_stream_mb.saturating_mul(1024 * 1024),
            allowed_hosts: config.allowed_direct_hosts.clone(),
        }
    }

    async fn ensure_public_target(&self, url_str: &str) -> Result<()> {
        if !self.allowed_hosts.is_empty() {
            return Ok(());
        }
        let parsed = Url::parse(url_str)
            .map_err(|_| BotError::NotFound(format!("invalid URL: {url_str}")))?;
        let host = parsed.host_str().unwrap_or("");
        if host.is_empty() || host.eq_ignore_ascii_case("localhost") || host.ends_with(".local") {
            return Err(BotError::NotFound(format!("blocked direct host '{host}'")));
        }
        let addrs: Vec<std::net::SocketAddr> = tokio::net::lookup_host((host, 0u16))
            .await
            .map_err(|_| BotError::NotFound(format!("could not resolve host '{host}'")))?
            .collect();
        for addr in addrs {
            if is_blocked_ip(addr.ip()) {
                return Err(BotError::NotFound(format!(
                    "host '{host}' resolves to private IP"
                )));
            }
        }
        Ok(())
    }

    async fn send_with_backoff(
        &self,
        make_request: impl FnOnce() -> reqwest::RequestBuilder,
    ) -> reqwest::Result<reqwest::Response> {
        let config = BackoffConfig {
            base_delay: Duration::from_millis(500),
            max_delay: Duration::from_secs(4),
            multiplier: 2.0,
            max_retries: 2,
            jitter_factor: 0.1,
        };

        let request = make_request().build()?;
        let client = self.client.clone();

        retry_with_backoff(
            || {
                let req = request
                    .try_clone()
                    .expect("empty-body GET/HEAD request is always cloneable");
                let client = client.clone();
                async move { client.execute(req).await }
            },
            is_retryable_reqwest_error,
            config,
        )
        .await
    }

    async fn probe(&self, url: &str) -> Result<reqwest::Response> {
        let head = tokio::time::timeout(
            Duration::from_secs(8),
            self.send_with_backoff(move || self.client.head(url)),
        )
        .await;
        match head {
            Ok(Ok(resp)) if resp.status().is_success() => return Ok(resp),
            Ok(Ok(resp)) => {
                let code = resp.status().as_u16();
                if code != 405 && code != 403 {
                    return Err(BotError::NotFound(format!(
                        "audio URL not reachable (HTTP {code})"
                    )));
                }
                debug!("HEAD not supported (HTTP {code}), falling back to ranged GET");
            }
            Ok(Err(e)) => {
                debug!("HEAD failed for {url}: {e}, falling back to ranged GET");
            }
            Err(_) => {
                return Err(BotError::NotFound(format!(
                    "HEAD request timed out for {url}"
                )))
            }
        }

        let get = self.send_with_backoff(move || {
            self.client
                .get(url)
                .header(reqwest::header::RANGE, "bytes=0-0")
        });
        match tokio::time::timeout(Duration::from_secs(8), get).await {
            Ok(Ok(resp)) if resp.status().is_success() => Ok(resp),
            Ok(Ok(resp)) => Err(BotError::NotFound(format!(
                "audio URL not reachable (HTTP {})",
                resp.status()
            ))),
            Ok(Err(e)) => Err(BotError::NotFound(format!("ranged GET failed: {e}"))),
            Err(_) => Err(BotError::NotFound(format!(
                "ranged GET timed out for {url}"
            ))),
        }
    }

    async fn validate(&self, url: &str) -> Result<()> {
        self.ensure_public_target(url).await?;
        let resp = self.probe(url).await?;

        if let Some(cl) = resp.headers().get(reqwest::header::CONTENT_LENGTH) {
            if let Ok(cl_str) = cl.to_str() {
                if let Ok(clen) = cl_str.trim().parse::<u64>() {
                    if clen > self.max_size_bytes {
                        return Err(BotError::NotFound(format!(
                            "audio stream exceeds max size ({} MB)",
                            self.max_size_bytes / (1024 * 1024)
                        )));
                    }
                }
            }
        }
        Ok(())
    }
}

fn derive_title(url: &str) -> String {
    let trimmed = url.trim_end_matches('/');
    let segment = trimmed.rsplit('/').next().unwrap_or(trimmed);
    let decoded = urlencoding::decode(segment).unwrap_or_else(|_| segment.into());
    let path = decoded.split(['?', '#']).next().unwrap_or(&decoded);
    let stem = match path.rsplit_once('.') {
        Some((s, _)) if !s.is_empty() => s,
        _ => path,
    };
    if stem.trim().is_empty() {
        url.to_string()
    } else {
        stem.trim().to_string()
    }
}

#[async_trait]
impl SourceAdapter for DirectResolver {
    fn name(&self) -> &'static str {
        "direct"
    }

    fn platform(&self) -> Platform {
        Platform::DirectUrl
    }

    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let query = query.trim();
        if !query.starts_with("http://") && !query.starts_with("https://") {
            return Err(BotError::NotFound("Not a direct audio URL".into()));
        }
        self.validate(query).await?;
        Ok(Track {
            id: TrackId::new(format!("direct:{query}")),
            title: derive_title(query),
            artist: None,
            url: query.to_string(),
            duration_secs: 0,
            thumbnail_url: None,
            requested_by,
            requested_by_name: requested_by_name.to_string(),
            source: SourceKind::DirectUrl,
            external_id: None,
        })
    }

    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio> {
        self.validate(&track.url).await?;
        Ok(ResolvedAudio {
            file_url: track.url.clone(),
            headers: None,
            is_direct: true,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;
    use std::sync::atomic::{AtomicU32, Ordering};

    #[test]
    fn blocks_private_and_reserved_ips() {
        for ip in [
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
            "100.64.0.1",
            "::1",
            "fd00::1",
            "fe80::1",
            "::ffff:10.0.0.5",
        ] {
            assert!(
                is_blocked_ip(IpAddr::from_str(ip).unwrap()),
                "{ip} must be blocked"
            );
        }
    }

    #[test]
    fn allows_public_ips() {
        for ip in ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"] {
            assert!(
                !is_blocked_ip(IpAddr::from_str(ip).unwrap()),
                "{ip} must be allowed"
            );
        }
    }

    #[tokio::test]
    async fn retries_on_transient_error() {
        let counter = AtomicU32::new(0);
        let config = BackoffConfig {
            base_delay: Duration::from_millis(10),
            max_delay: Duration::from_millis(100),
            multiplier: 2.0,
            max_retries: 3,
            jitter_factor: 0.0,
        };

        let result: std::result::Result<&str, &str> = retry_with_backoff(
            || async {
                let n = counter.fetch_add(1, Ordering::SeqCst);
                if n < 2 {
                    Err("transient")
                } else {
                    Ok("success")
                }
            },
            |_| true,
            config,
        )
        .await;

        assert_eq!(result.unwrap(), "success");
        assert_eq!(counter.load(Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn gives_up_after_max_retries() {
        let counter = AtomicU32::new(0);
        let config = BackoffConfig {
            base_delay: Duration::from_millis(10),
            max_delay: Duration::from_millis(100),
            multiplier: 2.0,
            max_retries: 2,
            jitter_factor: 0.0,
        };

        let result: std::result::Result<(), &str> = retry_with_backoff(
            || async {
                counter.fetch_add(1, Ordering::SeqCst);
                Err("permanent")
            },
            |_| true,
            config,
        )
        .await;

        assert!(result.is_err());
        assert_eq!(counter.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn parses_watch_url_query_param() {
        assert_eq!(
            YouTubeResolver::extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            Some("dQw4w9WgXcQ".to_string())
        );
    }

    #[test]
    fn parses_short_links_and_shorts() {
        assert_eq!(
            YouTubeResolver::extract_video_id("https://youtu.be/dQw4w9WgXcQ"),
            Some("dQw4w9WgXcQ".to_string())
        );
        assert_eq!(
            YouTubeResolver::extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            Some("dQw4w9WgXcQ".to_string())
        );
    }
}
