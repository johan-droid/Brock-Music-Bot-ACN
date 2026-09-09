use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

use crate::config::Config;
use crate::error::{BotError, Result};

// --- Domain Models ---

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TrackId(pub String);

impl TrackId {
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }
}

impl std::fmt::Display for TrackId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SourceKind {
    TelegramFile,
    YouTube,
    Spotify,
    AppleMusic,
    SoundCloud,
    DirectUrl,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Track {
    pub id: TrackId,
    pub title: String,
    pub artist: Option<String>,
    pub url: String,
    pub duration_secs: u64,
    pub thumbnail_url: Option<String>,
    pub requested_by: i64,
    pub requested_by_name: String,
    pub source: SourceKind,
    pub external_id: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ResolvedAudio {
    pub file_url: String,
    pub headers: Option<HashMap<String, String>>,
    pub is_direct: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Platform {
    YouTube,
    Spotify,
    AppleMusic,
    SoundCloud,
    DirectUrl,
}

impl Platform {
    pub fn all() -> [Platform; 5] {
        [
            Platform::YouTube,
            Platform::Spotify,
            Platform::AppleMusic,
            Platform::SoundCloud,
            Platform::DirectUrl,
        ]
    }

    pub fn name(&self) -> &'static str {
        match self {
            Platform::YouTube => "youtube",
            Platform::Spotify => "spotify",
            Platform::AppleMusic => "apple",
            Platform::SoundCloud => "soundcloud",
            Platform::DirectUrl => "direct",
        }
    }

    pub fn source_kind(&self) -> SourceKind {
        match self {
            Platform::YouTube => SourceKind::YouTube,
            Platform::Spotify => SourceKind::Spotify,
            Platform::AppleMusic => SourceKind::AppleMusic,
            Platform::SoundCloud => SourceKind::SoundCloud,
            Platform::DirectUrl => SourceKind::DirectUrl,
        }
    }

    pub fn from_source_kind(source: &SourceKind) -> Option<Platform> {
        match source {
            SourceKind::YouTube => Some(Platform::YouTube),
            SourceKind::Spotify => Some(Platform::Spotify),
            SourceKind::AppleMusic => Some(Platform::AppleMusic),
            SourceKind::SoundCloud => Some(Platform::SoundCloud),
            SourceKind::DirectUrl => Some(Platform::DirectUrl),
            SourceKind::TelegramFile => None,
        }
    }

    pub fn from_url(query: &str) -> Option<Platform> {
        let lower = query.to_lowercase();
        if lower.contains("youtu.be")
            || lower.contains("youtube.com")
            || lower.contains("youtube-nocookie.com")
            || lower.contains("music.youtube.com")
        {
            Some(Platform::YouTube)
        } else if lower.contains("open.spotify.com")
            || lower.contains("spotify.com")
            || lower.contains("spotify.link")
        {
            Some(Platform::Spotify)
        } else if lower.contains("music.apple.com")
            || lower.contains("itunes.apple.com")
            || lower.contains("apple.co")
        {
            Some(Platform::AppleMusic)
        } else if lower.contains("soundcloud.com") || lower.contains("snd.sc") {
            Some(Platform::SoundCloud)
        } else if lower.starts_with("http://") || lower.starts_with("https://") {
            Some(Platform::DirectUrl)
        } else {
            None
        }
    }
}

// --- Source Adapter Trait & Health Tracker ---

#[async_trait]
pub trait SourceAdapter: Send + Sync {
    fn name(&self) -> &'static str;
    fn platform(&self) -> Platform;
    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track>;
    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio>;
}

const SUCCESS_BONUS: f64 = 0.1;
const TRANSIENT_PENALTY: f64 = 0.7;
const HARD_PENALTY: f64 = 0.6;
const MAX_SCORE: f64 = 1.0;
const MIN_SCORE: f64 = 0.1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailureKind {
    Transient,
    Hard,
}

pub fn classify_error(err: &BotError) -> FailureKind {
    match err {
        BotError::RateLimited(_) | BotError::HttpClient(_) => FailureKind::Transient,
        _ => FailureKind::Hard,
    }
}

#[derive(Debug)]
pub struct ProviderHealth {
    inner: RwLock<HashMap<&'static str, f64>>,
}

impl ProviderHealth {
    pub fn new(names: impl IntoIterator<Item = &'static str>) -> Self {
        let inner = RwLock::new(
            names
                .into_iter()
                .map(|name| (name, MAX_SCORE))
                .collect::<HashMap<_, _>>(),
        );
        Self { inner }
    }

    pub fn score(&self, name: &str) -> f64 {
        self.inner
            .read()
            .map(|guard| guard.get(name).copied().unwrap_or(MAX_SCORE))
            .unwrap_or(MAX_SCORE)
    }

    pub fn record_success(&self, name: &'static str) {
        if let Ok(mut guard) = self.inner.write() {
            let score = guard.entry(name).or_insert(MAX_SCORE);
            *score = (*score + SUCCESS_BONUS).min(MAX_SCORE);
        }
    }

    pub fn record_failure(&self, name: &'static str, kind: FailureKind) {
        if let Ok(mut guard) = self.inner.write() {
            let score = guard.entry(name).or_insert(MAX_SCORE);
            let factor = match kind {
                FailureKind::Transient => TRANSIENT_PENALTY,
                FailureKind::Hard => HARD_PENALTY,
            };
            *score = (*score * factor).max(MIN_SCORE);
        }
    }
}

// --- Route Entry ---

pub struct Route {
    pub platform: Platform,
    pub adapter: Arc<dyn SourceAdapter>,
}

impl Route {
    pub fn new(platform: Platform, adapter: Arc<dyn SourceAdapter>) -> Self {
        Self { platform, adapter }
    }
}

// --- Music Router, URL Resolver, Video Resolver ---

/// Core Trait for resolving tracks.
#[async_trait]
pub trait TrackResolver: Send + Sync {
    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track>;
    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio>;
    async fn invalidate(&self, track: &Track);
}

/// Intelligence Layer 2: Intelligent Router
///
/// Reasons about available media sources — manages provider strategy, selection,
/// search ranking by health score, rate-limit awareness, and automatic fallbacks.
pub struct MusicRouter {
    routes: Vec<Route>,
    search_chain: Vec<Arc<dyn SourceAdapter>>,
    health: ProviderHealth,
    resolve_cache: Arc<DashMap<String, (Instant, ResolvedAudio)>>,
    resolve_cache_ttl: Duration,
    search_cache: Arc<DashMap<String, (Instant, Track)>>,
    search_cache_ttl: Duration,
    in_flight: Arc<DashMap<String, Arc<tokio::sync::Notify>>>,
}

impl MusicRouter {
    pub const MAX_STREAM_CACHE_TTL: Duration = Duration::from_secs(300);
    pub const SEARCH_CACHE_TTL: Duration = Duration::from_secs(3600);

    pub fn new(
        routes: Vec<Route>,
        search_chain: Vec<Arc<dyn SourceAdapter>>,
        config: &Config,
    ) -> Self {
        let health = ProviderHealth::new(
            routes
                .iter()
                .map(|r| r.adapter.name())
                .chain(search_chain.iter().map(|a| a.name())),
        );

        let resolve_cache_ttl =
            Duration::from_secs(config.stream_cache_ttl_secs).min(Self::MAX_STREAM_CACHE_TTL);

        Self {
            routes,
            search_chain,
            health,
            resolve_cache: Arc::new(DashMap::new()),
            resolve_cache_ttl,
            search_cache: Arc::new(DashMap::new()),
            search_cache_ttl: Self::SEARCH_CACHE_TTL,
            in_flight: Arc::new(DashMap::new()),
        }
    }

    #[allow(dead_code)]
    pub fn registered_platforms(&self) -> Vec<&'static str> {
        self.routes.iter().map(|r| r.platform.name()).collect()
    }

    fn route_for_url(&self, query: &str) -> Option<&Route> {
        let platform = Platform::from_url(query)?;
        self.routes.iter().find(|r| r.platform == platform)
    }

    fn route_for_source(&self, source: &SourceKind) -> Option<&Route> {
        let platform = Platform::from_source_kind(source)?;
        self.routes.iter().find(|r| r.platform == platform)
    }

    fn note_outcome<T>(&self, name: &'static str, result: &Result<T>) {
        match result {
            Ok(_) => self.health.record_success(name),
            Err(err) => self.health.record_failure(name, classify_error(err)),
        }
    }

    pub async fn execute_search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        if let Some(route) = self.route_for_url(query) {
            debug!(platform = route.platform.name(), query, "Routing URL query");
            let result = route
                .adapter
                .search(query, requested_by, requested_by_name)
                .await;
            self.note_outcome(route.adapter.name(), &result);
            return result;
        }

        if Platform::from_url(query).is_some() {
            return Err(BotError::NotFound(format!(
                "No adapter is enabled for platform '{}'",
                Platform::from_url(query).unwrap().name()
            )));
        }

        let mut ranked: Vec<Arc<dyn SourceAdapter>> = self.search_chain.clone();
        ranked.sort_by(|a, b| {
            self.health
                .score(b.name())
                .partial_cmp(&self.health.score(a.name()))
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut last_err = None;
        for adapter in ranked {
            debug!(
                provider = adapter.name(),
                query, "Trying provider in search chain"
            );
            match adapter.search(query, requested_by, requested_by_name).await {
                Ok(track) => {
                    self.health.record_success(adapter.name());
                    return Ok(track);
                }
                Err(err) => {
                    self.health
                        .record_failure(adapter.name(), classify_error(&err));
                    warn!(provider = adapter.name(), error = %err, "Search chain step failed");
                    last_err = Some(err);
                }
            }
        }

        Err(last_err
            .unwrap_or_else(|| BotError::NotFound(format!("No tracks found for query '{query}'"))))
    }
}

#[async_trait]
impl TrackResolver for MusicRouter {
    async fn search(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        let key = query.trim().to_lowercase();

        // 1. Check Search Cache
        if let Some((inserted, cached)) = self.search_cache.get(&key).as_deref() {
            if inserted.elapsed() < self.search_cache_ttl {
                debug!(query, "Search cache hit (avoided external API call)");
                let mut hit = cached.clone();
                hit.requested_by = requested_by;
                hit.requested_by_name = requested_by_name.to_string();
                return Ok(hit);
            }
            self.search_cache.remove(&key);
        }

        // 2. In-flight Request Deduplication (SingleFlight)
        if let Some(notify) = self.in_flight.get(&key).map(|r| r.value().clone()) {
            debug!(
                query,
                "Concurrent duplicate query detected; awaiting in-flight result"
            );
            notify.notified().await;
            if let Some((_, cached)) = self.search_cache.get(&key).as_deref() {
                let mut hit = cached.clone();
                hit.requested_by = requested_by;
                hit.requested_by_name = requested_by_name.to_string();
                return Ok(hit);
            }
        }

        let notify = Arc::new(tokio::sync::Notify::new());
        self.in_flight.insert(key.clone(), notify.clone());

        let res = self
            .execute_search(query, requested_by, requested_by_name)
            .await;

        if let Ok(ref track) = res {
            if self.search_cache.len() > 500 {
                let ttl = self.search_cache_ttl;
                self.search_cache
                    .retain(|_, (inserted, _)| inserted.elapsed() < ttl);
            }
            self.search_cache
                .insert(key.clone(), (Instant::now(), track.clone()));
        }

        self.in_flight.remove(&key);
        notify.notify_waiters();

        res
    }

    async fn resolve(&self, track: &Track) -> Result<ResolvedAudio> {
        if let Some((inserted_at, cached)) = self.resolve_cache.get(&track.id.0).as_deref() {
            if inserted_at.elapsed() < self.resolve_cache_ttl {
                debug!(track_id = %track.id, "Stream URL cache hit");
                return Ok(cached.clone());
            }
            self.resolve_cache.remove(&track.id.0);
        }

        let route = self.route_for_source(&track.source).ok_or_else(|| {
            BotError::Internal(format!(
                "No route registered for source kind {:?}",
                track.source
            ))
        })?;

        let res = route.adapter.resolve(track).await;
        self.note_outcome(route.adapter.name(), &res);
        if let Ok(audio) = &res {
            if self.resolve_cache.len() > 500 {
                let ttl = self.resolve_cache_ttl;
                self.resolve_cache
                    .retain(|_, (inserted, _)| inserted.elapsed() < ttl);
            }
            self.resolve_cache
                .insert(track.id.0.clone(), (Instant::now(), audio.clone()));
        }
        res
    }

    async fn invalidate(&self, track: &Track) {
        self.resolve_cache.remove(&track.id.0);
    }
}

/// URL Resolver: Direct URL & link resolver.
#[allow(dead_code)]
pub struct UrlResolver {
    pub router: Arc<MusicRouter>,
}

#[allow(dead_code)]
impl UrlResolver {
    pub fn new(router: Arc<MusicRouter>) -> Self {
        Self { router }
    }

    pub async fn resolve_url(
        &self,
        url: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        self.router
            .search(url, requested_by, requested_by_name)
            .await
    }
}

/// Video Resolver: Video search & URL resolver for /vplay commands.
#[allow(dead_code)]
pub struct VideoResolver {
    pub router: Arc<MusicRouter>,
}

#[allow(dead_code)]
impl VideoResolver {
    pub fn new(router: Arc<MusicRouter>) -> Self {
        Self { router }
    }

    pub async fn resolve_video(
        &self,
        query: &str,
        requested_by: i64,
        requested_by_name: &str,
    ) -> Result<Track> {
        self.router
            .search(query, requested_by, requested_by_name)
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_youtube_urls() {
        assert_eq!(
            Platform::from_url("https://youtu.be/dQw4w9WgXcQ"),
            Some(Platform::YouTube)
        );
        assert_eq!(
            Platform::from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            Some(Platform::YouTube)
        );
        assert_eq!(
            Platform::from_url("https://music.youtube.com/watch?v=abc"),
            Some(Platform::YouTube)
        );
    }

    #[test]
    fn classifies_spotify_urls() {
        assert_eq!(
            Platform::from_url("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"),
            Some(Platform::Spotify)
        );
        assert_eq!(
            Platform::from_url("https://spotify.link/abcd"),
            Some(Platform::Spotify)
        );
    }

    #[test]
    fn classifies_apple_and_soundcloud() {
        assert_eq!(
            Platform::from_url("https://music.apple.com/us/song/1440935467"),
            Some(Platform::AppleMusic)
        );
        assert_eq!(
            Platform::from_url("https://soundcloud.com/artist/song"),
            Some(Platform::SoundCloud)
        );
        assert_eq!(
            Platform::from_url("https://snd.sc/abcd"),
            Some(Platform::SoundCloud)
        );
    }

    #[test]
    fn classifies_direct_links_and_plain_queries() {
        assert_eq!(
            Platform::from_url("https://cdn.example.com/song.mp3"),
            Some(Platform::DirectUrl)
        );
        assert_eq!(
            Platform::from_url("https://radio.example.com/stream"),
            Some(Platform::DirectUrl)
        );
        assert_eq!(Platform::from_url("binks sake soul king"), None);
    }

    #[test]
    fn source_kind_mapping_roundtrips() {
        for platform in Platform::all() {
            assert_eq!(
                Platform::from_source_kind(&platform.source_kind()),
                Some(platform)
            );
        }
        assert_eq!(Platform::from_source_kind(&SourceKind::TelegramFile), None);
    }

    #[test]
    fn providers_start_at_full_health() {
        let health = ProviderHealth::new(["youtube", "spotify"]);
        assert_eq!(health.score("youtube"), 1.0);
        assert_eq!(health.score("spotify"), 1.0);
    }

    #[test]
    fn unknown_provider_defaults_to_full_health() {
        let health = ProviderHealth::new([]);
        assert_eq!(health.score("mystery"), 1.0);
    }

    #[test]
    fn success_recovery_is_capped_at_max() {
        let health = ProviderHealth::new(["youtube"]);
        for _ in 0..10 {
            health.record_success("youtube");
        }
        assert_eq!(health.score("youtube"), 1.0);
    }

    #[test]
    fn transient_penalty_is_softer_than_hard() {
        let health = ProviderHealth::new(["a", "b"]);
        health.record_failure("a", FailureKind::Transient);
        health.record_failure("b", FailureKind::Hard);
        assert!(health.score("a") > health.score("b"));
    }

    #[test]
    fn score_never_drops_below_floor() {
        let health = ProviderHealth::new(["a"]);
        for _ in 0..100 {
            health.record_failure("a", FailureKind::Hard);
        }
        assert_eq!(health.score("a"), MIN_SCORE);
    }
}
