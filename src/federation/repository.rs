use async_trait::async_trait;
use dashmap::DashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::RwLock;

use crate::error::Result;
use crate::federation::models::*;

fn current_timestamp() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}

#[async_trait]
pub trait FederationRepository: Send + Sync {
    // Lifecycle & Settings
    async fn create_federation(&self, fed: Federation) -> Result<Federation>;
    async fn get_federation(&self, fed_id: &str) -> Result<Option<Federation>>;
    async fn update_federation(&self, fed: Federation) -> Result<()>;
    async fn list_federations_by_owner(&self, owner_id: i64) -> Result<Vec<Federation>>;
    async fn list_public_federations(&self) -> Result<Vec<Federation>>;

    // Federation Chats
    async fn join_chat(&self, fed_id: &str, chat_id: i64, joined_by: i64) -> Result<()>;
    async fn leave_chat(&self, chat_id: i64) -> Result<Option<String>>;
    async fn get_chat_federation(&self, chat_id: i64) -> Result<Option<FederationChat>>;
    async fn list_federation_chats(&self, fed_id: &str) -> Result<Vec<FederationChat>>;
    async fn set_chat_quiet_mode(&self, chat_id: i64, quiet: bool) -> Result<bool>;

    // Federation Bans
    async fn add_ban(&self, ban: FederationBan) -> Result<FederationBan>;
    async fn remove_ban(&self, fed_id: &str, user_id: i64) -> Result<Option<FederationBan>>;
    async fn get_ban(&self, fed_id: &str, user_id: i64) -> Result<Option<FederationBan>>;
    async fn list_bans(&self, fed_id: &str) -> Result<Vec<FederationBan>>;
    async fn list_bans_for_user(&self, user_id: i64) -> Result<Vec<FederationBan>>;

    // Federation Subscriptions
    async fn add_subscription(&self, sub: FederationSubscription) -> Result<()>;
    async fn remove_subscription(&self, source_fed_id: &str, target_fed_id: &str) -> Result<bool>;
    async fn list_subscriptions(&self, source_fed_id: &str) -> Result<Vec<FederationSubscription>>;
    async fn list_reverse_subscriptions(&self, target_fed_id: &str) -> Result<Vec<FederationSubscription>>;

    // Federation Admins
    async fn add_admin(&self, fed_id: &str, user_id: i64, promoted_by: i64) -> Result<()>;
    async fn remove_admin(&self, fed_id: &str, user_id: i64) -> Result<bool>;
    async fn is_admin(&self, fed_id: &str, user_id: i64) -> Result<bool>;
    async fn list_admins(&self, fed_id: &str) -> Result<Vec<FederationAdmin>>;

    // Presence Tracking
    async fn record_presence(&self, chat_id: i64, user_id: i64, timestamp: i64) -> Result<()>;
    async fn is_user_seen_in_chat(&self, chat_id: i64, user_id: i64) -> Result<bool>;
    async fn list_seen_chats_for_user(&self, user_id: i64) -> Result<Vec<i64>>;

    // Audit Logging
    async fn log_event(&self, event: FederationEvent) -> Result<()>;
    async fn list_events(&self, fed_id: &str, limit: usize) -> Result<Vec<FederationEvent>>;

    // Enforcement Jobs
    async fn enqueue_job(&self, job: EnforcementJob) -> Result<()>;
    async fn update_job_status(&self, job_id: &str, status: EnforcementJobStatus, err: Option<String>) -> Result<()>;
    async fn get_pending_jobs(&self) -> Result<Vec<EnforcementJob>>;
}

pub struct MemoryFirstFederationRepository {
    federations: DashMap<String, Federation>,
    chat_associations: DashMap<i64, FederationChat>, // chat_id -> FederationChat
    bans: DashMap<String, FederationBan>,             // "fed_id:user_id" -> FederationBan
    subscriptions: DashMap<String, FederationSubscription>, // "source_fed_id:target_fed_id" -> Subscription
    admins: DashMap<String, FederationAdmin>,          // "fed_id:user_id" -> Admin
    presence: DashMap<String, ChatUserPresence>,      // "chat_id:user_id" -> Presence
    events: Arc<RwLock<Vec<FederationEvent>>>,
    jobs: DashMap<String, EnforcementJob>,             // job_id -> EnforcementJob
}

impl MemoryFirstFederationRepository {
    pub fn new() -> Self {
        Self {
            federations: DashMap::new(),
            chat_associations: DashMap::new(),
            bans: DashMap::new(),
            subscriptions: DashMap::new(),
            admins: DashMap::new(),
            presence: DashMap::new(),
            events: Arc::new(RwLock::new(Vec::new())),
            jobs: DashMap::new(),
        }
    }
}

impl Default for MemoryFirstFederationRepository {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl FederationRepository for MemoryFirstFederationRepository {
    async fn create_federation(&self, fed: Federation) -> Result<Federation> {
        self.federations.insert(fed.id.clone(), fed.clone());
        Ok(fed)
    }

    async fn get_federation(&self, fed_id: &str) -> Result<Option<Federation>> {
        Ok(self.federations.get(fed_id).map(|r| r.clone()))
    }

    async fn update_federation(&self, fed: Federation) -> Result<()> {
        self.federations.insert(fed.id.clone(), fed);
        Ok(())
    }

    async fn list_federations_by_owner(&self, owner_id: i64) -> Result<Vec<Federation>> {
        let feds = self
            .federations
            .iter()
            .filter(|r| r.owner_user_id == owner_id && r.status == FederationStatus::Active)
            .map(|r| r.clone())
            .collect();
        Ok(feds)
    }

    async fn list_public_federations(&self) -> Result<Vec<Federation>> {
        let feds = self
            .federations
            .iter()
            .filter(|r| r.status == FederationStatus::Active && r.visibility == FederationVisibility::Public)
            .map(|r| r.clone())
            .collect();
        Ok(feds)
    }

    async fn join_chat(&self, fed_id: &str, chat_id: i64, joined_by: i64) -> Result<()> {
        let now = current_timestamp();
        let fc = FederationChat {
            federation_id: fed_id.to_string(),
            chat_id,
            joined_at: now,
            joined_by,
            status: "active".to_string(),
            quiet_mode: false,
        };
        self.chat_associations.insert(chat_id, fc);
        Ok(())
    }

    async fn leave_chat(&self, chat_id: i64) -> Result<Option<String>> {
        if let Some((_, fc)) = self.chat_associations.remove(&chat_id) {
            Ok(Some(fc.federation_id))
        } else {
            Ok(None)
        }
    }

    async fn get_chat_federation(&self, chat_id: i64) -> Result<Option<FederationChat>> {
        Ok(self.chat_associations.get(&chat_id).map(|r| r.clone()))
    }

    async fn list_federation_chats(&self, fed_id: &str) -> Result<Vec<FederationChat>> {
        let chats = self
            .chat_associations
            .iter()
            .filter(|r| r.federation_id == fed_id && r.status == "active")
            .map(|r| r.clone())
            .collect();
        Ok(chats)
    }

    async fn set_chat_quiet_mode(&self, chat_id: i64, quiet: bool) -> Result<bool> {
        if let Some(mut fc) = self.chat_associations.get_mut(&chat_id) {
            fc.quiet_mode = quiet;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    async fn add_ban(&self, ban: FederationBan) -> Result<FederationBan> {
        let key = format!("{}:{}", ban.federation_id, ban.user_id);
        self.bans.insert(key, ban.clone());
        Ok(ban)
    }

    async fn remove_ban(&self, fed_id: &str, user_id: i64) -> Result<Option<FederationBan>> {
        let key = format!("{}:{}", fed_id, user_id);
        if let Some(mut ban) = self.bans.get_mut(&key) {
            ban.status = FederationBanStatus::Removed;
            ban.updated_at = current_timestamp();
            ban.version += 1;
            Ok(Some(ban.clone()))
        } else {
            Ok(None)
        }
    }

    async fn get_ban(&self, fed_id: &str, user_id: i64) -> Result<Option<FederationBan>> {
        let key = format!("{}:{}", fed_id, user_id);
        Ok(self
            .bans
            .get(&key)
            .filter(|b| b.status == FederationBanStatus::Active)
            .map(|b| b.clone()))
    }

    async fn list_bans(&self, fed_id: &str) -> Result<Vec<FederationBan>> {
        let res = self
            .bans
            .iter()
            .filter(|b| b.federation_id == fed_id && b.status == FederationBanStatus::Active)
            .map(|b| b.clone())
            .collect();
        Ok(res)
    }

    async fn list_bans_for_user(&self, user_id: i64) -> Result<Vec<FederationBan>> {
        let res = self
            .bans
            .iter()
            .filter(|b| b.user_id == user_id && b.status == FederationBanStatus::Active)
            .map(|b| b.clone())
            .collect();
        Ok(res)
    }

    async fn add_subscription(&self, sub: FederationSubscription) -> Result<()> {
        let key = format!("{}:{}", sub.source_fed_id, sub.target_fed_id);
        self.subscriptions.insert(key, sub);
        Ok(())
    }

    async fn remove_subscription(&self, source_fed_id: &str, target_fed_id: &str) -> Result<bool> {
        let key = format!("{}:{}", source_fed_id, target_fed_id);
        Ok(self.subscriptions.remove(&key).is_some())
    }

    async fn list_subscriptions(&self, source_fed_id: &str) -> Result<Vec<FederationSubscription>> {
        let res = self
            .subscriptions
            .iter()
            .filter(|s| s.source_fed_id == source_fed_id)
            .map(|s| s.clone())
            .collect();
        Ok(res)
    }

    async fn list_reverse_subscriptions(&self, target_fed_id: &str) -> Result<Vec<FederationSubscription>> {
        let res = self
            .subscriptions
            .iter()
            .filter(|s| s.target_fed_id == target_fed_id)
            .map(|s| s.clone())
            .collect();
        Ok(res)
    }

    async fn add_admin(&self, fed_id: &str, user_id: i64, promoted_by: i64) -> Result<()> {
        let key = format!("{}:{}", fed_id, user_id);
        let admin = FederationAdmin {
            federation_id: fed_id.to_string(),
            user_id,
            promoted_at: current_timestamp(),
            promoted_by,
        };
        self.admins.insert(key, admin);
        Ok(())
    }

    async fn remove_admin(&self, fed_id: &str, user_id: i64) -> Result<bool> {
        let key = format!("{}:{}", fed_id, user_id);
        Ok(self.admins.remove(&key).is_some())
    }

    async fn is_admin(&self, fed_id: &str, user_id: i64) -> Result<bool> {
        let key = format!("{}:{}", fed_id, user_id);
        Ok(self.admins.contains_key(&key))
    }

    async fn list_admins(&self, fed_id: &str) -> Result<Vec<FederationAdmin>> {
        let res = self
            .admins
            .iter()
            .filter(|a| a.federation_id == fed_id)
            .map(|a| a.clone())
            .collect();
        Ok(res)
    }

    async fn record_presence(&self, chat_id: i64, user_id: i64, timestamp: i64) -> Result<()> {
        let key = format!("{}:{}", chat_id, user_id);
        if let Some(mut p) = self.presence.get_mut(&key) {
            p.last_seen_at = timestamp;
        } else {
            let p = ChatUserPresence {
                chat_id,
                user_id,
                first_seen_at: timestamp,
                last_seen_at: timestamp,
            };
            self.presence.insert(key, p);
        }
        Ok(())
    }

    async fn is_user_seen_in_chat(&self, chat_id: i64, user_id: i64) -> Result<bool> {
        let key = format!("{}:{}", chat_id, user_id);
        Ok(self.presence.contains_key(&key))
    }

    async fn list_seen_chats_for_user(&self, user_id: i64) -> Result<Vec<i64>> {
        let chats = self
            .presence
            .iter()
            .filter(|p| p.user_id == user_id)
            .map(|p| p.chat_id)
            .collect();
        Ok(chats)
    }

    async fn log_event(&self, event: FederationEvent) -> Result<()> {
        let mut events = self.events.write().await;
        events.push(event);
        Ok(())
    }

    async fn list_events(&self, fed_id: &str, limit: usize) -> Result<Vec<FederationEvent>> {
        let events = self.events.read().await;
        let res = events
            .iter()
            .rev()
            .filter(|e| e.federation_id == fed_id)
            .take(limit)
            .cloned()
            .collect();
        Ok(res)
    }

    async fn enqueue_job(&self, job: EnforcementJob) -> Result<()> {
        self.jobs.insert(job.job_id.clone(), job);
        Ok(())
    }

    async fn update_job_status(&self, job_id: &str, status: EnforcementJobStatus, err: Option<String>) -> Result<()> {
        if let Some(mut j) = self.jobs.get_mut(job_id) {
            j.status = status;
            j.error_message = err;
        }
        Ok(())
    }

    async fn get_pending_jobs(&self) -> Result<Vec<EnforcementJob>> {
        let pending = self
            .jobs
            .iter()
            .filter(|j| j.status == EnforcementJobStatus::Pending)
            .map(|j| j.clone())
            .collect();
        Ok(pending)
    }
}
