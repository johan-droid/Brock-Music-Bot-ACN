use std::collections::VecDeque;
use std::sync::Arc;
use dashmap::DashMap;
use rand::seq::SliceRandom;
use rand::thread_rng;
use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoopMode {
    Off,
    Track,
    Queue,
}

impl Default for LoopMode {
    fn default() -> Self {
        LoopMode::Off
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Track {
    pub id: String,
    pub title: String,
    pub artist: String,
    pub url: String,
    pub duration: u64,
    pub thumbnail: String,
    pub requested_by: i64,
    pub requested_by_name: String,
    pub source: String,
}

#[derive(Debug, Clone, Default)]
pub struct ChatQueueState {
    pub current: Option<Track>,
    pub queue: VecDeque<Track>,
    pub history: Vec<Track>,
    pub loop_mode: LoopMode,
    pub volume: u32,
    pub is_paused: bool,
}

impl ChatQueueState {
    pub fn new() -> Self {
        Self {
            current: None,
            queue: VecDeque::new(),
            history: Vec::new(),
            loop_mode: LoopMode::Off,
            volume: 100,
            is_paused: false,
        }
    }

    pub fn enqueue(&mut self, track: Track) -> usize {
        self.queue.push_back(track);
        self.queue.len()
    }

    pub fn enqueue_front(&mut self, track: Track) {
        self.queue.push_front(track);
    }

    pub fn next_track(&mut self) -> Option<Track> {
        match self.loop_mode {
            LoopMode::Track => {
                if let Some(curr) = &self.current {
                    return Some(curr.clone());
                }
            }
            LoopMode::Queue => {
                if let Some(curr) = self.current.take() {
                    self.history.push(curr.clone());
                    self.queue.push_back(curr);
                }
            }
            LoopMode::Off => {
                if let Some(curr) = self.current.take() {
                    self.history.push(curr);
                }
            }
        }

        let next = self.queue.pop_front();
        self.current = next.clone();
        next
    }

    pub fn prev_track(&mut self) -> Option<Track> {
        if let Some(prev) = self.history.pop() {
            if let Some(curr) = self.current.take() {
                self.queue.push_front(curr);
            }
            self.current = Some(prev.clone());
            Some(prev)
        } else {
            None
        }
    }

    pub fn shuffle(&mut self) {
        let mut slice: Vec<_> = self.queue.drain(..).collect();
        let mut rng = thread_rng();
        slice.shuffle(&mut rng);
        self.queue = slice.into();
    }

    pub fn remove(&mut self, index: usize) -> Option<Track> {
        if index < self.queue.len() {
            self.queue.remove(index)
        } else {
            None
        }
    }

    pub fn move_track(&mut self, from: usize, to: usize) -> bool {
        if from >= self.queue.len() || to >= self.queue.len() {
            return false;
        }
        if let Some(track) = self.queue.remove(from) {
            self.queue.insert(to, track);
            true
        } else {
            false
        }
    }

    pub fn clear(&mut self) {
        self.queue.clear();
    }
}

#[derive(Clone, Default)]
pub struct QueueManager {
    chats: Arc<DashMap<i64, Arc<RwLock<ChatQueueState>>>>,
}

impl QueueManager {
    pub fn new() -> Self {
        Self {
            chats: Arc::new(DashMap::new()),
        }
    }

    pub async fn get_or_create(&self, chat_id: i64) -> Arc<RwLock<ChatQueueState>> {
        self.chats
            .entry(chat_id)
            .or_insert_with(|| Arc::new(RwLock::new(ChatQueueState::new())))
            .value()
            .clone()
    }

    pub fn active_chats(&self) -> Vec<i64> {
        self.chats.iter().map(|entry| *entry.key()).collect()
    }

    pub async fn remove_chat(&self, chat_id: i64) {
        self.chats.remove(&chat_id);
    }
}
