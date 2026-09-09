use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use dashmap::DashMap;
use rand::seq::SliceRandom;
use rand::thread_rng;
use serde::{Deserialize, Serialize};
use teloxide::prelude::*;
use tgcalls::{Calls, TgCallsError};
use tokio::sync::RwLock;
use tracing::{info, warn};

use crate::config::Config;
use crate::error::{BotError, Result};
use crate::router::{Track, TrackResolver};

// --- Loop Mode & Playback State ---

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoopMode {
    Off,
    Track,
    Queue,
}

impl LoopMode {
    pub fn cycle(self) -> Self {
        match self {
            LoopMode::Off => LoopMode::Track,
            LoopMode::Track => LoopMode::Queue,
            LoopMode::Queue => LoopMode::Off,
        }
    }

    pub fn display_text(self) -> &'static str {
        match self {
            LoopMode::Off => "Off ➡️",
            LoopMode::Track => "Track 🔂",
            LoopMode::Queue => "Queue 🔁",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum VoiceState {
    Disconnected,
    Connecting,
    Connected,
    Streaming,
    Leaving,
    Failed,
}

impl VoiceState {
    pub fn display_text(self) -> &'static str {
        match self {
            VoiceState::Disconnected => "DISCONNECTED 🔴",
            VoiceState::Connecting => "CONNECTING 🟡",
            VoiceState::Connected => "CONNECTED 🟢",
            VoiceState::Streaming => "STREAMING 🔊",
            VoiceState::Leaving => "LEAVING 🟠",
            VoiceState::Failed => "FAILED ⚠️",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EngineState {
    Idle,
    Joining,
    Queued,
    Ready,
    Loading,
    Playing,
    Paused,
    Skipping,
    Stopping,
    WaitingForVc,
    Disconnected,
    Recovering,
    Finished,
    Error,
}

impl EngineState {
    pub fn display_text(self) -> &'static str {
        match self {
            EngineState::Idle => "IDLE",
            EngineState::Joining => "JOINING",
            EngineState::Queued => "QUEUED",
            EngineState::Ready => "READY",
            EngineState::Loading => "LOADING",
            EngineState::Playing => "PLAYING",
            EngineState::Paused => "PAUSED",
            EngineState::Skipping => "SKIPPING",
            EngineState::Stopping => "STOPPING",
            EngineState::WaitingForVc => "WAITING FOR VC",
            EngineState::Disconnected => "DISCONNECTED",
            EngineState::Recovering => "RECOVERING",
            EngineState::Finished => "FINISHED",
            EngineState::Error => "ERROR",
        }
    }
}

#[derive(Debug, Clone)]
pub struct PlaybackState {
    pub current: Option<Track>,
    pub position_secs: u64,
    pub is_paused: bool,
    pub loop_mode: LoopMode,
    pub volume: u32,
    pub queue_len: usize,
    pub history_len: usize,
    pub engine_state: EngineState,
    pub voice_state: VoiceState,
    pub playback_generation: u64,
    pub vc_generation: u64,
    pub owner_user_id: Option<i64>,
    pub owner_user_name: String,
    pub session_id: String,
    pub last_error: Option<String>,
    pub player_message_id: Option<i32>,
    pub queue: Vec<Track>,
}

pub const HISTORY_LIMIT: usize = 50;
pub const UNKNOWN_DURATION_LIMIT_SECS: u64 = 600;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TransitionReason {
    Eof,
    Skip,
    Failure,
    UserAction,
}

// --- Chat Queue State ---

#[derive(Debug, Clone)]
pub struct ChatQueueState {
    pub current: Option<Track>,
    pub queue: VecDeque<Track>,
    pub history: Vec<Track>,
    pub loop_mode: LoopMode,
    pub volume: u32,
    pub is_paused: bool,
    pub position_secs: u64,
    pub engine_state: EngineState,
    pub voice_state: VoiceState,
    pub playback_generation: u64,
    pub vc_generation: u64,
    pub owner_user_id: Option<i64>,
    pub owner_user_name: String,
    pub session_id: String,
    pub transition_in_progress: bool,
    pub last_error: Option<String>,
    pub player_message_id: Option<i32>,
    max_queue_size: usize,
}

impl ChatQueueState {
    pub fn new(max_queue_size: usize, default_volume: u32) -> Self {
        Self {
            current: None,
            queue: VecDeque::new(),
            history: Vec::new(),
            loop_mode: LoopMode::Off,
            volume: default_volume,
            is_paused: false,
            position_secs: 0,
            engine_state: EngineState::Idle,
            voice_state: VoiceState::Disconnected,
            playback_generation: 0,
            vc_generation: 0,
            owner_user_id: None,
            owner_user_name: String::new(),
            session_id: uuid::Uuid::new_v4().to_string(),
            transition_in_progress: false,
            last_error: None,
            player_message_id: None,
            max_queue_size,
        }
    }

    pub fn set_session_owner(&mut self, user_id: i64, user_name: &str) {
        if self.owner_user_id.is_none() {
            info!(
                "[SESSION] Assigned session controller: user_id={}, name='{}'",
                user_id, user_name
            );
            self.owner_user_id = Some(user_id);
            self.owner_user_name = user_name.to_string();
        }
    }

    pub fn begin_transition(&mut self, target_state: EngineState) -> bool {
        if self.transition_in_progress {
            info!(
                "[PLAYBACK] transition already in progress, ignoring duplicate transition to {:?}",
                target_state
            );
            return false;
        }
        let prev = self.engine_state;
        self.transition_in_progress = true;
        self.engine_state = target_state;
        info!("[PLAYBACK] state: {:?} -> {:?}", prev, target_state);
        true
    }

    pub fn end_transition(&mut self, final_state: EngineState) {
        let prev = self.engine_state;
        self.engine_state = final_state;
        self.transition_in_progress = false;
        info!("[PLAYBACK] state: {:?} -> {:?}", prev, final_state);
    }

    pub fn assert_invariants(&mut self) {
        if self.engine_state == EngineState::Playing && self.current.is_none() {
            warn!("[INVARIANT_VIOLATION] EngineState is Playing but current track is None! Self-healing state -> IDLE");
            self.engine_state = EngineState::Idle;
            self.transition_in_progress = false;
        }

        if self.current.is_none()
            && self.queue.is_empty()
            && self.voice_state == VoiceState::Disconnected
            && self.engine_state != EngineState::Idle
        {
            info!("[INVARIANT_VIOLATION] Disconnected & empty queue state contradiction! Self-healing state -> IDLE");
            self.engine_state = EngineState::Idle;
            self.transition_in_progress = false;
        }
    }

    pub fn reconcile(&mut self) {
        if self.voice_state == VoiceState::Disconnected
            && (self.engine_state == EngineState::Playing
                || self.engine_state == EngineState::Paused)
        {
            info!("[RECONCILE] Playing/Paused state contradiction detected while VC is Disconnected; invalidating generation and resetting runtime state");
            self.playback_generation += 1;
            self.transition_in_progress = false;
            self.is_paused = false;
            if let Some(curr) = self.current.take() {
                info!(
                    "[RECONCILE] preserving interrupted active track '{}' at queue head",
                    curr.title
                );
                self.queue.push_front(curr);
            }
            self.position_secs = 0;
            self.engine_state = if self.queue.is_empty() {
                EngineState::Idle
            } else {
                EngineState::WaitingForVc
            };
        }

        if self.current.is_none()
            && self.queue.is_empty()
            && self.engine_state != EngineState::Idle
            && self.engine_state != EngineState::WaitingForVc
        {
            info!("[RECONCILE] empty queue and no active track detected; resetting engine_state to IDLE");
            self.engine_state = EngineState::Idle;
            self.transition_in_progress = false;
        }

        self.assert_invariants();
    }

    pub fn enqueue(&mut self, mut track: Track) -> Option<usize> {
        if self.queue.len() >= self.max_queue_size {
            return None;
        }
        // Assign unique runtime TrackId so identical song requests are distinct queue items
        track.id = crate::router::TrackId::new(format!("{}_{}", track.id.0, uuid::Uuid::new_v4()));
        let pos = self.queue.len() + 1;
        self.queue.push_back(track);
        if self.engine_state == EngineState::Idle && self.current.is_none() {
            self.engine_state = EngineState::Queued;
        }
        info!("[QUEUE] remaining: {}", self.queue.len());
        Some(pos)
    }

    pub fn tick_seconds(&mut self, secs: u64) -> bool {
        let Some(track) = self.current.as_ref() else {
            return false;
        };
        if self.is_paused {
            return false;
        }
        self.position_secs += secs;
        let effective_duration = if track.duration_secs == 0 {
            UNKNOWN_DURATION_LIMIT_SECS
        } else {
            track.duration_secs
        };

        if self.position_secs >= effective_duration {
            self.position_secs = 0;
            true
        } else {
            false
        }
    }

    pub fn next_track(&mut self) -> Option<Track> {
        if let Some(curr) = self.current.take() {
            info!("[QUEUE] removing completed track: '{}'", curr.title);
            match self.loop_mode {
                LoopMode::Queue => {
                    self.queue.push_back(curr);
                }
                LoopMode::Off | LoopMode::Track => {
                    self.history.push(curr);
                    if self.history.len() > HISTORY_LIMIT {
                        self.history.remove(0);
                    }
                }
            }
        }
        let next = self.queue.pop_front();
        self.current = next.clone();
        self.position_secs = 0;

        if let Some(ref t) = next {
            self.engine_state = EngineState::Playing;
            info!(
                "[PLAYBACK] state: -> PLAYING, current: '{}', remaining queue: {}",
                t.title,
                self.queue.len()
            );
        } else {
            self.engine_state = EngineState::Idle;
            info!("[PLAYBACK] state: -> IDLE, queue empty");
        }
        next
    }

    pub fn skip(&mut self) -> Result<Option<Track>> {
        self.playback_generation += 1;
        if self.current.is_none() && self.queue.is_empty() {
            info!("[COMMAND] /skip called when no track is playing or queued; queue unchanged");
            return Err(BotError::NotFound(
                "Nothing is currently playing or queued".to_string(),
            ));
        }

        if !self.begin_transition(EngineState::Skipping) {
            info!("[PLAYBACK] ignoring duplicate skip transition");
            return Ok(self.current.clone());
        }

        let skipped_track = self.current.take();
        if let Some(track) = skipped_track {
            info!("[COMMAND] /skip: skipping track '{}'", track.title);
            info!("[QUEUE] removed skipped track: '{}'", track.title);
            match self.loop_mode {
                LoopMode::Queue => {
                    self.queue.push_back(track);
                }
                LoopMode::Off | LoopMode::Track => {
                    self.history.push(track);
                    if self.history.len() > HISTORY_LIMIT {
                        self.history.remove(0);
                    }
                }
            }
        }

        let next = self.queue.pop_front();
        self.current = next.clone();
        self.position_secs = 0;

        let final_state = if let Some(ref t) = next {
            info!(
                "[QUEUE] next track: '{}', remaining queue: {}",
                t.title,
                self.queue.len()
            );
            EngineState::Playing
        } else {
            info!("[QUEUE] queue empty, state settling to IDLE");
            EngineState::Idle
        };

        self.end_transition(final_state);
        Ok(next)
    }

    pub fn on_voice_disconnected(&mut self) {
        info!("[VOICE] voice disconnected event received, invalidating playback generation");
        self.voice_state = VoiceState::Disconnected;
        self.playback_generation += 1;
        self.transition_in_progress = false;

        if let Some(curr) = self.current.take() {
            info!(
                "[VOICE] preserving disconnected active track '{}' at head of queue",
                curr.title
            );
            self.queue.push_front(curr);
        }
        self.position_secs = 0;
        self.engine_state = if self.queue.is_empty() {
            EngineState::Idle
        } else {
            EngineState::WaitingForVc
        };
    }

    pub fn prev_track(&mut self) -> Option<Track> {
        if let Some(prev) = self.history.pop() {
            if let Some(curr) = self.current.take() {
                self.queue.push_front(curr);
            }
            self.current = Some(prev.clone());
            self.position_secs = 0;
            self.engine_state = EngineState::Playing;
            Some(prev)
        } else {
            None
        }
    }

    pub fn tick(&mut self) -> Option<u64> {
        let track = self.current.as_ref()?;
        if self.is_paused {
            return Some(self.position_secs);
        }
        self.position_secs += 1;
        let effective_duration = if track.duration_secs == 0 {
            UNKNOWN_DURATION_LIMIT_SECS
        } else {
            track.duration_secs
        };
        if self.position_secs >= effective_duration {
            self.position_secs = 0;
            self.on_track_end();
        }
        Some(self.position_secs)
    }

    pub fn set_position(&mut self, secs: u64) {
        let duration = self.current.as_ref().map(|t| t.duration_secs).unwrap_or(0);
        self.position_secs = if duration > 0 {
            secs.min(duration.saturating_sub(1))
        } else {
            secs
        };
    }

    pub fn clear_current(&mut self) -> Option<Track> {
        let current = self.current.take();
        self.position_secs = 0;
        if self.queue.is_empty() {
            self.engine_state = EngineState::Idle;
        }
        current
    }

    pub fn on_track_end(&mut self) -> Option<Track> {
        if let Some(ref curr) = self.current {
            info!("[PLAYBACK] EOF: '{}'", curr.title);
        }
        match self.loop_mode {
            LoopMode::Track => {
                let track = self.current.clone();
                self.position_secs = 0;
                if let Some(ref t) = track {
                    info!("[PLAYBACK] loop mode TRACK: replaying '{}'", t.title);
                }
                track
            }
            LoopMode::Off | LoopMode::Queue => self.next_track(),
        }
    }

    pub fn reset(&mut self) {
        if let Some(ref curr) = self.current {
            info!("[PLAYBACK] stopping active track: '{}'", curr.title);
        }
        self.current = None;
        self.queue.clear();
        self.history.clear();
        self.position_secs = 0;
        self.is_paused = false;
        self.engine_state = EngineState::Idle;
        self.voice_state = VoiceState::Disconnected;
        self.playback_generation += 1;
        self.owner_user_id = None;
        self.owner_user_name = String::new();
        self.session_id = uuid::Uuid::new_v4().to_string();
        self.transition_in_progress = false;
        info!("[PLAYBACK] state: -> IDLE, stage cleared");
    }

    pub fn shuffle(&mut self) {
        let mut vec: Vec<Track> = self.queue.drain(..).collect();
        vec.shuffle(&mut thread_rng());
        self.queue = vec.into();
    }
}

// --- Queue Repository ---

pub struct InMemoryQueueRepository {
    queues: DashMap<i64, Arc<RwLock<ChatQueueState>>>,
    max_queue_size: usize,
    default_volume: u32,
}

impl InMemoryQueueRepository {
    pub fn new(max_queue_size: usize, default_volume: u32) -> Self {
        Self {
            queues: DashMap::new(),
            max_queue_size,
            default_volume,
        }
    }

    pub fn prune_inactive_sessions(&self, _max_idle: Duration) {
        self.queues.retain(|chat_id, queue_arc| {
            if let Ok(lock) = queue_arc.try_read() {
                let is_active = lock.engine_state == EngineState::Playing
                    || lock.engine_state == EngineState::Loading
                    || lock.voice_state == VoiceState::Connected
                    || lock.current.is_some()
                    || !lock.queue.is_empty();
                if is_active {
                    true
                } else {
                    info!(
                        chat_id,
                        "[PRUNE] Evicting inactive idle chat session from memory"
                    );
                    false
                }
            } else {
                true
            }
        });
    }

    pub fn get_or_create(&self, chat_id: i64) -> Arc<RwLock<ChatQueueState>> {
        self.queues
            .entry(chat_id)
            .or_insert_with(|| {
                Arc::new(RwLock::new(ChatQueueState::new(
                    self.max_queue_size,
                    self.default_volume,
                )))
            })
            .clone()
    }

    pub async fn enqueue(&self, chat_id: i64, track: Track) -> Result<Option<usize>> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        Ok(lock.enqueue(track))
    }

    pub async fn get_current(&self, chat_id: i64) -> Result<Option<Track>> {
        let state = self.get_or_create(chat_id);
        let lock = state.read().await;
        Ok(lock.current.clone())
    }

    pub async fn next_track(&self, chat_id: i64) -> Result<Option<Track>> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        Ok(lock.next_track())
    }

    pub async fn skip_track(&self, chat_id: i64) -> Result<Option<Track>> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.skip()
    }

    pub async fn prev_track(&self, chat_id: i64) -> Result<Option<Track>> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        Ok(lock.prev_track())
    }

    pub async fn clear_current(&self, chat_id: i64) -> Result<Option<Track>> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        Ok(lock.clear_current())
    }

    pub async fn clear(&self, chat_id: i64) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.reset();
        Ok(())
    }

    pub async fn set_paused(&self, chat_id: i64, paused: bool) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.is_paused = paused;
        if paused {
            lock.engine_state = EngineState::Paused;
        } else if lock.current.is_some() {
            lock.engine_state = EngineState::Playing;
        }
        Ok(())
    }

    pub async fn set_volume(&self, chat_id: i64, volume: u32) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.volume = volume;
        Ok(())
    }

    pub async fn tick_seconds(&self, chat_id: i64, seconds: u64) -> Result<bool> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        Ok(lock.tick_seconds(seconds))
    }

    pub async fn set_position(&self, chat_id: i64, seconds: u64) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.set_position(seconds);
        Ok(())
    }

    pub async fn cycle_loop_mode(&self, chat_id: i64) -> Result<LoopMode> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.loop_mode = lock.loop_mode.cycle();
        Ok(lock.loop_mode)
    }

    pub async fn shuffle(&self, chat_id: i64) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.shuffle();
        Ok(())
    }

    pub async fn set_voice_state(&self, chat_id: i64, voice_state: VoiceState) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.voice_state = voice_state;
        Ok(())
    }

    pub async fn on_voice_disconnected(&self, chat_id: i64) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.on_voice_disconnected();
        Ok(())
    }

    pub async fn set_session_owner(
        &self,
        chat_id: i64,
        user_id: i64,
        user_name: &str,
    ) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.set_session_owner(user_id, user_name);
        Ok(())
    }

    pub async fn set_player_message_id(&self, chat_id: i64, message_id: Option<i32>) -> Result<()> {
        let state = self.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.player_message_id = message_id;
        Ok(())
    }

    pub async fn get_playback_state(&self, chat_id: i64) -> Result<PlaybackState> {
        let state = self.get_or_create(chat_id);
        let lock = state.read().await;
        Ok(PlaybackState {
            current: lock.current.clone(),
            position_secs: lock.position_secs,
            is_paused: lock.is_paused,
            loop_mode: lock.loop_mode,
            volume: lock.volume,
            queue_len: lock.queue.len(),
            history_len: lock.history.len(),
            engine_state: lock.engine_state,
            voice_state: lock.voice_state,
            playback_generation: lock.playback_generation,
            vc_generation: lock.vc_generation,
            owner_user_id: lock.owner_user_id,
            owner_user_name: lock.owner_user_name.clone(),
            session_id: lock.session_id.clone(),
            last_error: lock.last_error.clone(),
            player_message_id: lock.player_message_id,
            queue: lock.queue.iter().cloned().collect(),
        })
    }

    pub fn active_chats(&self) -> Vec<i64> {
        self.queues.iter().map(|kv| *kv.key()).collect()
    }

    pub fn inner(&self) -> &Self {
        self
    }
}

// --- Stream Download Manager ---

// --- Voice Chat Transport ---

#[derive(Debug, Clone)]
pub struct DeliveryReceipt {
    pub message_id: Option<i32>,
}

#[async_trait]
pub trait PlaybackTransport: Send + Sync {
    async fn deliver(&self, chat_id: i64, track: &Track) -> Result<DeliveryReceipt>;
    async fn pause(&self, chat_id: i64) -> Result<()>;
    async fn resume(&self, chat_id: i64) -> Result<()>;
    async fn stop(&self, chat_id: i64) -> Result<()>;
    async fn seek(&self, chat_id: i64, track: &Track, seconds: u64) -> Result<()>;
    async fn set_volume(&self, chat_id: i64, volume: u32) -> Result<()>;
}

pub struct VoiceChatTransport {
    calls: Calls,
    _bot: Option<Bot>,
    resolver: Arc<dyn TrackResolver>,
    _shutdown: ferogram::ShutdownToken,
}

impl VoiceChatTransport {
    #[allow(dead_code)]
    pub fn new(
        calls: Calls,
        bot: Option<Bot>,
        resolver: Arc<dyn TrackResolver>,
        shutdown: ferogram::ShutdownToken,
    ) -> Self {
        Self {
            calls,
            _bot: bot,
            resolver,
            _shutdown: shutdown,
        }
    }

    #[allow(dead_code)]
    pub async fn shutdown_all(&self) {
        let results = self.calls.shutdown().await;
        for (chat_id, res) in results {
            match res {
                Ok(()) => info!(chat_id, "Left voice chat"),
                Err(e) => warn!(chat_id, error = %e, "Failed to leave voice chat"),
            }
        }
    }
}

#[allow(dead_code)]
pub async fn connect_voice_transport(
    config: &Config,
    bot: Option<Bot>,
    resolver: Arc<dyn TrackResolver>,
) -> Option<VoiceChatTransport> {
    info!("[VOICE] Initializing MTProto assistant");
    let (Some(api_id), Some(api_hash)) = (config.tg_api_id, config.tg_api_hash.as_deref()) else {
        warn!("[VOICE] Voice transport disabled: TG_API_ID or TG_API_HASH not set");
        return None;
    };
    info!("[VOICE] API credentials loaded (api_id: {})", api_id);

    let builder = ferogram::Client::builder()
        .api_id(api_id)
        .api_hash(api_hash);
    let builder = if let Some(s) = config
        .assistant_session_string
        .as_deref()
        .filter(|s| !s.is_empty())
    {
        info!("[VOICE] Assistant session loaded from string");
        builder.session_string(s)
    } else {
        info!(
            "[VOICE] Assistant session loaded from file path: {}",
            config.assistant_session
        );
        builder.session(&config.assistant_session)
    };

    let (client, shutdown) = match builder.connect().await {
        Ok(pair) => {
            info!("[VOICE] MTProto connected successfully");
            pair
        }
        Err(e) => {
            warn!(error = %e, "[VOICE] MTProto connect failed; voice transport disabled");
            return None;
        }
    };

    match client.is_authorized().await {
        Ok(true) => {
            info!("[VOICE] Authorization confirmed");
        }
        Ok(false) => {
            warn!("[VOICE] Assistant session is NOT authorized");
            return None;
        }
        Err(e) => {
            warn!(error = %e, "[VOICE] Failed to check authorization state");
            return None;
        }
    }

    info!("[VOICE] tgcalls transport initialized");
    let calls = Calls::with_concurrency_limit(client, 1);
    info!("[VOICE] Voice transport READY");
    Some(VoiceChatTransport::new(calls, bot, resolver, shutdown))
}

fn map_voice_err(e: TgCallsError, _chat_id: i64) -> BotError {
    match &e {
        TgCallsError::NotJoined => {
            BotError::NotFound("not connected to the voice chat".to_string())
        }
        TgCallsError::NoActiveGroupCall => {
            BotError::NotFound("no active voice chat in this group".to_string())
        }
        TgCallsError::TooManyConcurrentCalls(limit) => BotError::RateLimited(format!(
            "assistant already streaming in {limit} voice chat(s)"
        )),
        _ => BotError::Internal(format!("voice chat error: {e}")),
    }
}

#[async_trait]
impl PlaybackTransport for VoiceChatTransport {
    async fn deliver(&self, chat_id: i64, track: &Track) -> Result<DeliveryReceipt> {
        let resolved = self.resolver.resolve(track).await?;
        info!(chat_id, track_id = %track.id, file_url = %resolved.file_url, "Streaming direct URL into voice chat");

        let play_res = self.calls.play(chat_id, resolved.file_url.clone()).await;
        if let Err(e) = play_res {
            self.resolver.invalidate(track).await;
            return Err(map_voice_err(e, chat_id));
        }
        Ok(DeliveryReceipt { message_id: None })
    }

    async fn pause(&self, chat_id: i64) -> Result<()> {
        self.calls
            .pause(chat_id)
            .await
            .map_err(|e| map_voice_err(e, chat_id))
    }

    async fn resume(&self, chat_id: i64) -> Result<()> {
        self.calls
            .resume(chat_id)
            .await
            .map_err(|e| map_voice_err(e, chat_id))
    }

    async fn stop(&self, chat_id: i64) -> Result<()> {
        match self.calls.leave(chat_id).await {
            Ok(()) | Err(TgCallsError::NotJoined) => Ok(()),
            Err(e) => Err(map_voice_err(e, chat_id)),
        }
    }

    async fn seek(&self, chat_id: i64, track: &Track, seconds: u64) -> Result<()> {
        let resolved = self.resolver.resolve(track).await?;
        let seek_res = self
            .calls
            .seek(
                chat_id,
                resolved.file_url.clone(),
                Duration::from_secs(seconds),
            )
            .await;
        if let Err(e) = seek_res {
            self.resolver.invalidate(track).await;
            return Err(map_voice_err(e, chat_id));
        }
        Ok(())
    }

    async fn set_volume(&self, _chat_id: i64, _volume: u32) -> Result<()> {
        Ok(())
    }
}

/// Unavailable Voice Transport: Explicitly fails when no MTProto voice transport is connected.
pub struct UnavailableVoiceTransport {
    reason: String,
}

impl UnavailableVoiceTransport {
    pub fn new(reason: impl Into<String>) -> Self {
        Self {
            reason: reason.into(),
        }
    }
}

#[async_trait]
impl PlaybackTransport for UnavailableVoiceTransport {
    async fn deliver(&self, _chat_id: i64, _track: &Track) -> Result<DeliveryReceipt> {
        Err(BotError::Internal(format!(
            "Voice transport unavailable: {}",
            self.reason
        )))
    }
    async fn pause(&self, _chat_id: i64) -> Result<()> {
        Err(BotError::Internal(format!(
            "Voice transport unavailable: {}",
            self.reason
        )))
    }
    async fn resume(&self, _chat_id: i64) -> Result<()> {
        Err(BotError::Internal(format!(
            "Voice transport unavailable: {}",
            self.reason
        )))
    }
    async fn stop(&self, _chat_id: i64) -> Result<()> {
        Ok(())
    }
    async fn seek(&self, _chat_id: i64, _track: &Track, _seconds: u64) -> Result<()> {
        Err(BotError::Internal(format!(
            "Voice transport unavailable: {}",
            self.reason
        )))
    }
    async fn set_volume(&self, _chat_id: i64, _volume: u32) -> Result<()> {
        Ok(())
    }
}

/// Mock Playback Transport: For unit tests that verify queue/engine logic without voice calls.
#[allow(dead_code)]
pub struct MockPlaybackTransport;

#[allow(dead_code)]
impl MockPlaybackTransport {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl PlaybackTransport for MockPlaybackTransport {
    async fn deliver(&self, _chat_id: i64, _track: &Track) -> Result<DeliveryReceipt> {
        Ok(DeliveryReceipt { message_id: None })
    }
    async fn pause(&self, _chat_id: i64) -> Result<()> {
        Ok(())
    }
    async fn resume(&self, _chat_id: i64) -> Result<()> {
        Ok(())
    }
    async fn stop(&self, _chat_id: i64) -> Result<()> {
        Ok(())
    }
    async fn seek(&self, _chat_id: i64, _track: &Track, _seconds: u64) -> Result<()> {
        Ok(())
    }
    async fn set_volume(&self, _chat_id: i64, _volume: u32) -> Result<()> {
        Ok(())
    }
}

// --- Media Engine ---

/// Media Engine: Owns Queue State, Download Stream, Playback State & Controls.
pub struct MediaEngine {
    pub repo: Arc<InMemoryQueueRepository>,
    pub transport: Arc<dyn PlaybackTransport>,
}

impl MediaEngine {
    pub fn new(repo: Arc<InMemoryQueueRepository>, transport: Arc<dyn PlaybackTransport>) -> Self {
        Self { repo, transport }
    }

    pub async fn reconcile_session(&self, chat_id: i64) -> Result<PlaybackState> {
        let state = self.repo.get_or_create(chat_id);
        let mut lock = state.write().await;
        lock.reconcile();
        drop(lock);
        self.repo.get_playback_state(chat_id).await
    }

    pub async fn set_session_owner(
        &self,
        chat_id: i64,
        user_id: i64,
        user_name: &str,
    ) -> Result<()> {
        self.repo
            .set_session_owner(chat_id, user_id, user_name)
            .await
    }

    pub async fn enqueue_and_play(&self, chat_id: i64, track: Track) -> Result<Option<usize>> {
        let _ = self
            .repo
            .set_session_owner(chat_id, track.requested_by, &track.requested_by_name)
            .await;

        let is_idle = {
            let state = self.repo.get_or_create(chat_id);
            let lock = state.read().await;
            lock.current.is_none()
                && lock.engine_state != EngineState::Playing
                && lock.engine_state != EngineState::Loading
        };

        let pos = self.repo.enqueue(chat_id, track).await?;

        if is_idle {
            let _ = self
                .advance_to_next_track(chat_id, TransitionReason::UserAction)
                .await?;
            Ok(None)
        } else {
            Ok(pos)
        }
    }

    pub async fn play(&self, chat_id: i64, track: &Track) -> Result<()> {
        match self.transport.deliver(chat_id, track).await {
            Ok(_) => {
                let _ = self
                    .repo
                    .set_voice_state(chat_id, VoiceState::Connected)
                    .await;
                Ok(())
            }
            Err(e) => {
                let _ = self.repo.on_voice_disconnected(chat_id).await;
                let _ = self.transport.stop(chat_id).await;
                Err(e)
            }
        }
    }

    pub async fn on_voice_disconnected(&self, chat_id: i64) -> Result<()> {
        self.repo.on_voice_disconnected(chat_id).await?;
        let _ = self.transport.stop(chat_id).await;
        Ok(())
    }

    pub async fn pause(&self, chat_id: i64) -> Result<()> {
        self.transport.pause(chat_id).await?;
        self.repo.set_paused(chat_id, true).await
    }

    pub async fn resume(&self, chat_id: i64) -> Result<()> {
        self.transport.resume(chat_id).await?;
        self.repo.set_paused(chat_id, false).await
    }

    pub async fn advance_to_next_track(
        &self,
        chat_id: i64,
        reason: TransitionReason,
    ) -> Result<Option<Track>> {
        let state = self.repo.get_or_create(chat_id);
        let mut lock = state.write().await;

        if lock.transition_in_progress {
            info!(
                chat_id,
                ?reason,
                "[TRANSITION] transition already in progress, ignoring duplicate request"
            );
            return Ok(lock.current.clone());
        }

        lock.transition_in_progress = true;
        lock.playback_generation += 1;
        let gen = lock.playback_generation;

        info!(
            chat_id,
            ?reason,
            generation = gen,
            curr = ?lock.current.as_ref().map(|t| t.title.as_str()),
            queue_len = lock.queue.len(),
            "[TRANSITION] starting atomic track transition"
        );

        if let Some(old_curr) = lock.current.take() {
            info!(chat_id, title = %old_curr.title, "[TRANSITION] cleaning up completed/skipped track");
            match lock.loop_mode {
                LoopMode::Queue => {
                    lock.queue.push_back(old_curr);
                }
                LoopMode::Track if reason == TransitionReason::Eof => {
                    lock.queue.push_front(old_curr);
                }
                _ => {
                    lock.history.push(old_curr);
                    if lock.history.len() > HISTORY_LIMIT {
                        lock.history.remove(0);
                    }
                }
            }
        }

        let next_track = lock.queue.pop_front();
        lock.current = next_track.clone();
        lock.position_secs = 0;

        if let Some(ref t) = next_track {
            lock.engine_state = EngineState::Loading;
            info!(chat_id, next = %t.title, remaining_queue = lock.queue.len(), "[TRANSITION] selected next track, state -> LOADING");
        } else {
            lock.engine_state = EngineState::Idle;
            lock.transition_in_progress = false;
            info!(chat_id, "[TRANSITION] queue empty, state -> IDLE");
            drop(lock);
            let _ = self.transport.stop(chat_id).await;
            return Ok(None);
        }

        let track_to_deliver = next_track.clone().unwrap();
        drop(lock);

        match self.transport.deliver(chat_id, &track_to_deliver).await {
            Ok(_) => {
                let mut lock = state.write().await;
                if lock.playback_generation == gen {
                    lock.engine_state = EngineState::Playing;
                    lock.voice_state = VoiceState::Connected;
                    lock.transition_in_progress = false;
                    info!(chat_id, track = %track_to_deliver.title, "[TRANSITION] delivery success, state -> PLAYING");
                } else {
                    info!(chat_id, "[TRANSITION] generation token changed during delivery; discarding state update");
                }
                Ok(Some(track_to_deliver))
            }
            Err(e) => {
                warn!(chat_id, error = %e, track = %track_to_deliver.title, "[TRANSITION] delivery failed; advancing to next track recursively");
                let mut lock = state.write().await;
                if lock.playback_generation == gen {
                    lock.transition_in_progress = false;
                }
                drop(lock);

                Box::pin(self.advance_to_next_track(chat_id, TransitionReason::Failure)).await
            }
        }
    }

    pub async fn skip(&self, chat_id: i64) -> Result<Option<Track>> {
        self.advance_to_next_track(chat_id, TransitionReason::Skip)
            .await
    }

    pub async fn on_natural_end_with_generation(
        &self,
        chat_id: i64,
        expected_generation: u64,
    ) -> Result<Option<Track>> {
        let gen = {
            let state = self.repo.get_or_create(chat_id);
            let lock = state.read().await;
            lock.playback_generation
        };
        if gen != expected_generation {
            info!(
                chat_id,
                expected = expected_generation,
                current = gen,
                "[PLAYBACK] generation token mismatch; discarding stale EOF callback"
            );
            let state = self.repo.get_or_create(chat_id);
            let lock = state.read().await;
            return Ok(lock.current.clone());
        }
        self.advance_to_next_track(chat_id, TransitionReason::Eof)
            .await
    }

    pub async fn on_natural_end(&self, chat_id: i64) -> Result<Option<Track>> {
        self.advance_to_next_track(chat_id, TransitionReason::Eof)
            .await
    }

    pub async fn prev(&self, chat_id: i64) -> Result<Option<Track>> {
        let prev = self.repo.prev_track(chat_id).await?;
        if let Some(track) = &prev {
            self.transport.deliver(chat_id, track).await?;
        }
        Ok(prev)
    }

    pub async fn stop(&self, chat_id: i64) -> Result<()> {
        self.repo.clear(chat_id).await?;
        self.transport.stop(chat_id).await
    }

    pub async fn seek(&self, chat_id: i64, seconds: u64) -> Result<()> {
        let track = self
            .repo
            .get_current(chat_id)
            .await?
            .ok_or_else(|| BotError::NotFound("No track currently playing".to_string()))?;
        self.transport.seek(chat_id, &track, seconds).await?;
        self.repo.set_position(chat_id, seconds).await
    }

    pub async fn set_volume(&self, chat_id: i64, volume: u32) -> Result<()> {
        self.repo.set_volume(chat_id, volume).await?;
        self.transport.set_volume(chat_id, volume).await
    }

    pub async fn state(&self, chat_id: i64) -> Result<PlaybackState> {
        self.repo.get_playback_state(chat_id).await
    }
}
