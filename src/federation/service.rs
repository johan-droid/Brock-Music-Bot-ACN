use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use teloxide::prelude::*;
use teloxide::types::ParseMode;
use uuid::Uuid;

use crate::error::{BotError, Result};
use crate::federation::models::*;
use crate::federation::repository::FederationRepository;
use crate::federation::resolver::FederationBanResolver;

pub const MAX_FEDERATION_SUBSCRIPTIONS: usize = 5;

fn current_timestamp() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}

pub struct FederationService {
    repo: Arc<dyn FederationRepository>,
    resolver: FederationBanResolver,
    bot: Option<Bot>,
}

impl FederationService {
    pub fn new(repo: Arc<dyn FederationRepository>, bot: Option<Bot>) -> Self {
        let resolver = FederationBanResolver::new(repo.clone());
        Self { repo, resolver, bot }
    }

    pub fn repository(&self) -> &Arc<dyn FederationRepository> {
        &self.repo
    }

    pub fn resolver(&self) -> &FederationBanResolver {
        &self.resolver
    }

    // --- Authorization Helpers ---
    pub async fn verify_owner(&self, fed_id: &str, requester_id: i64) -> Result<Federation> {
        let fed = self
            .repo
            .get_federation(fed_id)
            .await?
            .ok_or_else(|| BotError::NotFound(format!("Federation '{fed_id}' not found")))?;

        if fed.status != FederationStatus::Active {
            return Err(BotError::Unauthorized(format!(
                "Federation '{fed_id}' is deleted"
            )));
        }

        if fed.owner_user_id != requester_id {
            return Err(BotError::Unauthorized(format!(
                "Only the federation owner (ID {}) can perform this operation",
                fed.owner_user_id
            )));
        }

        Ok(fed)
    }

    pub async fn verify_owner_or_admin(&self, fed_id: &str, requester_id: i64) -> Result<Federation> {
        let fed = self
            .repo
            .get_federation(fed_id)
            .await?
            .ok_or_else(|| BotError::NotFound(format!("Federation '{fed_id}' not found")))?;

        if fed.status != FederationStatus::Active {
            return Err(BotError::Unauthorized(format!(
                "Federation '{fed_id}' is deleted"
            )));
        }

        if fed.owner_user_id == requester_id || self.repo.is_admin(fed_id, requester_id).await? {
            Ok(fed)
        } else {
            Err(BotError::Unauthorized(
                "You must be a federation owner or federation admin to perform this action".into(),
            ))
        }
    }

    // --- Federation Lifecycle ---
    pub async fn create_federation(
        &self,
        name: String,
        owner_user_id: i64,
        description: Option<String>,
    ) -> Result<Federation> {
        let fed_id = Uuid::new_v4().to_string();
        let now = current_timestamp();
        let fed = Federation {
            id: fed_id.clone(),
            name,
            description,
            owner_user_id,
            created_at: now,
            updated_at: now,
            status: FederationStatus::Active,
            visibility: FederationVisibility::Public,
            settings: FederationSettings::default(),
            log_chat_id: None,
        };

        let created = self.repo.create_federation(fed).await?;
        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: fed_id,
                event_type: FederationEventType::FedCreated,
                actor_user_id: owner_user_id,
                target_user_id: None,
                target_chat_id: None,
                metadata: Some(format!("Created federation '{}'", created.name)),
                created_at: now,
            })
            .await?;

        Ok(created)
    }

    pub async fn delete_federation(&self, fed_id: &str, requester_id: i64) -> Result<()> {
        let mut fed = self.verify_owner(fed_id, requester_id).await?;
        fed.status = FederationStatus::Deleted;
        fed.updated_at = current_timestamp();
        self.repo.update_federation(fed).await?;

        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: fed_id.to_string(),
                event_type: FederationEventType::FedDeleted,
                actor_user_id: requester_id,
                target_user_id: None,
                target_chat_id: None,
                metadata: Some("Soft deleted federation".into()),
                created_at: current_timestamp(),
            })
            .await?;

        Ok(())
    }

    pub async fn get_federation_info(&self, fed_id: &str) -> Result<Federation> {
        self.repo
            .get_federation(fed_id)
            .await?
            .ok_or_else(|| BotError::NotFound(format!("Federation '{fed_id}' not found")))
    }

    pub async fn list_public_federations(&self) -> Result<Vec<Federation>> {
        self.repo.list_public_federations().await
    }

    // --- Joining & Leaving Chats ---
    pub async fn join_chat(&self, fed_id: &str, chat_id: i64, requester_id: i64) -> Result<()> {
        let fed = self
            .repo
            .get_federation(fed_id)
            .await?
            .ok_or_else(|| BotError::NotFound(format!("Federation '{fed_id}' not found")))?;

        if fed.status != FederationStatus::Active {
            return Err(BotError::Unauthorized("Federation is inactive/deleted".into()));
        }

        if let Some(existing) = self.repo.get_chat_federation(chat_id).await? {
            if existing.federation_id == fed_id {
                return Err(BotError::Internal("Chat is already in this federation".into()));
            } else {
                return Err(BotError::Internal(format!(
                    "Chat is already part of another federation (ID: {}). Leave that federation first.",
                    existing.federation_id
                )));
            }
        }

        self.repo.join_chat(fed_id, chat_id, requester_id).await?;
        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: fed_id.to_string(),
                event_type: FederationEventType::ChatJoined,
                actor_user_id: requester_id,
                target_user_id: None,
                target_chat_id: Some(chat_id),
                metadata: None,
                created_at: current_timestamp(),
            })
            .await?;

        self.notify_owner(&fed, &format!("💬 Chat `{chat_id}` joined federation `{}`", fed.name)).await;

        Ok(())
    }

    pub async fn leave_chat(&self, chat_id: i64, requester_id: i64) -> Result<String> {
        let existing = self
            .repo
            .get_chat_federation(chat_id)
            .await?
            .ok_or_else(|| BotError::NotFound("Chat is not currently in any federation".into()))?;

        let fed_id = existing.federation_id.clone();
        self.repo.leave_chat(chat_id).await?;

        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: fed_id.clone(),
                event_type: FederationEventType::ChatLeft,
                actor_user_id: requester_id,
                target_user_id: None,
                target_chat_id: Some(chat_id),
                metadata: None,
                created_at: current_timestamp(),
            })
            .await?;

        Ok(fed_id)
    }

    pub async fn set_quiet_mode(&self, chat_id: i64, quiet: bool) -> Result<()> {
        let _ = self
            .repo
            .get_chat_federation(chat_id)
            .await?
            .ok_or_else(|| BotError::NotFound("Chat is not in a federation".into()))?;

        self.repo.set_chat_quiet_mode(chat_id, quiet).await?;
        Ok(())
    }

    // --- Federation Bans (OWNER ONLY FOR MUTATION) ---
    pub async fn fban(
        &self,
        fed_id: &str,
        target_user_id: i64,
        target_username: Option<String>,
        reason: String,
        requester_id: i64,
    ) -> Result<(FederationBan, usize, usize)> {
        // STRICT RULE: ONLY FEDERATION OWNER CAN FBAN
        let fed = self.verify_owner(fed_id, requester_id).await?;

        let clean_reason = reason.trim().to_string();
        if fed.settings.require_reason && clean_reason.is_empty() {
            return Err(BotError::Unauthorized(
                "This federation requires a reason for federation bans. Use `/fban <user> <reason>`".into(),
            ));
        }

        let reason_final = if clean_reason.is_empty() {
            "No reason provided".to_string()
        } else {
            clean_reason
        };

        let now = current_timestamp();
        let existing_ban = self.repo.get_ban(fed_id, target_user_id).await?;
        let version = existing_ban.map(|b| b.version + 1).unwrap_or(1);

        let ban = FederationBan {
            id: Uuid::new_v4().to_string(),
            federation_id: fed_id.to_string(),
            user_id: target_user_id,
            username: target_username.clone(),
            reason: reason_final.clone(),
            created_by: requester_id,
            created_at: now,
            updated_at: now,
            status: FederationBanStatus::Active,
            version,
        };

        let saved = self.repo.add_ban(ban).await?;

        // Active enforcement across participating chats
        let chats = self.repo.list_federation_chats(fed_id).await?;
        let mut total_chats = 0;
        let mut relevant_chats = 0;

        for fc in chats {
            total_chats += 1;
            // Determine if user was seen in this chat
            let seen = self.repo.is_user_seen_in_chat(fc.chat_id, target_user_id).await?;
            if seen {
                relevant_chats += 1;
                let job = EnforcementJob {
                    job_id: Uuid::new_v4().to_string(),
                    federation_id: fed_id.to_string(),
                    user_id: target_user_id,
                    target_chat_id: fc.chat_id,
                    reason: reason_final.clone(),
                    quiet_mode: fc.quiet_mode,
                    expected_version: version,
                    created_at: now,
                    status: EnforcementJobStatus::Pending,
                    error_message: None,
                };
                self.repo.enqueue_job(job).await?;
            }
        }

        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: fed_id.to_string(),
                event_type: FederationEventType::FedbanCreated,
                actor_user_id: requester_id,
                target_user_id: Some(target_user_id),
                target_chat_id: None,
                metadata: Some(format!("Reason: {}", reason_final)),
                created_at: now,
            })
            .await?;

        self.notify_owner(
            &fed,
            &format!(
                "🚫 <b>Fedban Issued</b>\nTarget: <code>{target_user_id}</code>\nReason: {reason_final}\nEnforcement queued in {relevant_chats}/{total_chats} chats"
            ),
        )
        .await;

        Ok((saved, total_chats, relevant_chats))
    }

    pub async fn unfban(&self, fed_id: &str, target_user_id: i64, requester_id: i64) -> Result<FederationBan> {
        // STRICT RULE: ONLY FEDERATION OWNER CAN UNFBAN
        let fed = self.verify_owner(fed_id, requester_id).await?;

        let removed = self
            .repo
            .remove_ban(fed_id, target_user_id)
            .await?
            .ok_or_else(|| BotError::NotFound(format!("User {target_user_id} is not fanned in federation {fed_id}")))?;

        let now = current_timestamp();
        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: fed_id.to_string(),
                event_type: FederationEventType::FedbanRemoved,
                actor_user_id: requester_id,
                target_user_id: Some(target_user_id),
                target_chat_id: None,
                metadata: None,
                created_at: now,
            })
            .await?;

        self.notify_owner(
            &fed,
            &format!("✅ <b>Fedban Removed</b>\nTarget: <code>{target_user_id}</code>"),
        )
        .await;

        Ok(removed)
    }

    // --- Subscriptions ---
    pub async fn add_subscription(
        &self,
        source_fed_id: &str,
        target_fed_id: &str,
        requester_id: i64,
    ) -> Result<()> {
        let source_fed = self.verify_owner(source_fed_id, requester_id).await?;

        let _target_fed = self
            .repo
            .get_federation(target_fed_id)
            .await?
            .ok_or_else(|| BotError::NotFound(format!("Target federation '{target_fed_id}' not found")))?;

        let current_subs = self.repo.list_subscriptions(source_fed_id).await?;
        if current_subs.len() >= MAX_FEDERATION_SUBSCRIPTIONS {
            return Err(BotError::Unauthorized(format!(
                "Maximum subscription limit of {MAX_FEDERATION_SUBSCRIPTIONS} reached for federation"
            )));
        }

        if self
            .resolver
            .check_subscription_cycle(source_fed_id, target_fed_id)
            .await?
        {
            return Err(BotError::Unauthorized(
                "Subscription rejected: adding this subscription creates a circular dependency (cycle) in the federation DAG"
                    .into(),
            ));
        }

        let now = current_timestamp();
        let sub = FederationSubscription {
            source_fed_id: source_fed_id.to_string(),
            target_fed_id: target_fed_id.to_string(),
            created_at: now,
            created_by: requester_id,
        };

        self.repo.add_subscription(sub).await?;
        self.repo
            .log_event(FederationEvent {
                id: Uuid::new_v4().to_string(),
                federation_id: source_fed_id.to_string(),
                event_type: FederationEventType::SubfedAdded,
                actor_user_id: requester_id,
                target_user_id: None,
                target_chat_id: None,
                metadata: Some(format!("Subscribed to fed '{target_fed_id}'")),
                created_at: now,
            })
            .await?;

        self.notify_owner(
            &source_fed,
            &format!("🔗 Subscribed to federation `{target_fed_id}`"),
        )
        .await;

        Ok(())
    }

    pub async fn remove_subscription(
        &self,
        source_fed_id: &str,
        target_fed_id: &str,
        requester_id: i64,
    ) -> Result<bool> {
        let source_fed = self.verify_owner(source_fed_id, requester_id).await?;

        let removed = self.repo.remove_subscription(source_fed_id, target_fed_id).await?;
        if removed {
            let now = current_timestamp();
            self.repo
                .log_event(FederationEvent {
                    id: Uuid::new_v4().to_string(),
                    federation_id: source_fed_id.to_string(),
                    event_type: FederationEventType::SubfedRemoved,
                    actor_user_id: requester_id,
                    target_user_id: None,
                    target_chat_id: None,
                    metadata: Some(format!("Unsubscribed from fed '{target_fed_id}'")),
                    created_at: now,
                })
                .await?;

            self.notify_owner(
                &source_fed,
                &format!("✂️ Unsubscribed from federation `{target_fed_id}`"),
            )
            .await;
        }

        Ok(removed)
    }

    // --- Federation Admins (Support/View only, NO FBAN) ---
    pub async fn add_admin(&self, fed_id: &str, target_user_id: i64, requester_id: i64) -> Result<()> {
        let fed = self.verify_owner(fed_id, requester_id).await?;
        self.repo.add_admin(fed_id, target_user_id, requester_id).await?;

        self.notify_owner(
            &fed,
            &format!("👤 Promoted user <code>{target_user_id}</code> to federation admin"),
        )
        .await;
        Ok(())
    }

    pub async fn remove_admin(&self, fed_id: &str, target_user_id: i64, requester_id: i64) -> Result<bool> {
        let fed = self.verify_owner(fed_id, requester_id).await?;
        let removed = self.repo.remove_admin(fed_id, target_user_id).await?;
        if removed {
            self.notify_owner(
                &fed,
                &format!("👤 Demoted federation admin <code>{target_user_id}</code>"),
            )
            .await;
        }
        Ok(removed)
    }

    // --- Settings & Audit Logging ---
    pub async fn set_reason_required(&self, fed_id: &str, required: bool, requester_id: i64) -> Result<()> {
        let mut fed = self.verify_owner(fed_id, requester_id).await?;
        fed.settings.require_reason = required;
        fed.updated_at = current_timestamp();
        self.repo.update_federation(fed).await?;
        Ok(())
    }

    pub async fn set_log_chat(&self, fed_id: &str, log_chat_id: Option<i64>, requester_id: i64) -> Result<()> {
        let mut fed = self.verify_owner(fed_id, requester_id).await?;
        fed.log_chat_id = log_chat_id;
        fed.updated_at = current_timestamp();
        self.repo.update_federation(fed).await?;
        Ok(())
    }

    // --- Ban List Export & Import ---
    pub async fn export_fban_list(&self, fed_id: &str, format: &str) -> Result<String> {
        let bans = self.repo.list_bans(fed_id).await?;
        match format.to_lowercase().as_str() {
            "csv" | "minicsv" => {
                let mut out = String::from("user_id,username,reason\n");
                for b in bans {
                    let u = b.username.as_deref().unwrap_or("");
                    out.push_str(&format!("{},\"{}\",\"{}\"\n", b.user_id, u, b.reason));
                }
                Ok(out)
            }
            "json" => {
                let json_data = serde_json::to_string_pretty(&bans)
                    .map_err(|e| BotError::Internal(format!("Failed to serialize bans: {e}")))?;
                Ok(json_data)
            }
            "jsonl" | "ndjson" => {
                let mut out = String::new();
                for b in bans {
                    let line = serde_json::to_string(&b)
                        .map_err(|e| BotError::Internal(format!("Failed to serialize line: {e}")))?;
                    out.push_str(&line);
                    out.push('\n');
                }
                Ok(out)
            }
            _ => Err(BotError::Internal(format!(
                "Unsupported format '{format}'. Supported formats: csv, json, jsonl"
            ))),
        }
    }

    pub async fn import_fban_list(
        &self,
        fed_id: &str,
        content: &str,
        requester_id: i64,
    ) -> Result<(usize, usize, usize)> {
        // STRICT RULE: ONLY FEDERATION OWNER CAN IMPORT FBANS
        let _fed = self.verify_owner(fed_id, requester_id).await?;

        let mut valid_count = 0;
        let mut duplicate_count = 0;
        let mut invalid_count = 0;

        let now = current_timestamp();

        // Check if JSON format
        if content.trim_start().starts_with('[') {
            if let Ok(parsed_bans) = serde_json::from_str::<Vec<serde_json::Value>>(content) {
                for item in parsed_bans {
                    if let Some(user_id) = item.get("user_id").and_then(|v| v.as_i64()) {
                        let reason = item
                            .get("reason")
                            .and_then(|v| v.as_str())
                            .unwrap_or("Imported ban")
                            .to_string();
                        let username = item.get("username").and_then(|v| v.as_str()).map(String::from);

                        if self.repo.get_ban(fed_id, user_id).await?.is_some() {
                            duplicate_count += 1;
                        } else {
                            let ban = FederationBan {
                                id: Uuid::new_v4().to_string(),
                                federation_id: fed_id.to_string(),
                                user_id,
                                username,
                                reason,
                                created_by: requester_id,
                                created_at: now,
                                updated_at: now,
                                status: FederationBanStatus::Active,
                                version: 1,
                            };
                            let _ = self.repo.add_ban(ban).await;
                            valid_count += 1;
                        }
                    } else {
                        invalid_count += 1;
                    }
                }
                return Ok((valid_count, duplicate_count, invalid_count));
            }
        }

        // Process line by line (CSV / JSONL)
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with("user_id") {
                continue;
            }

            if trimmed.starts_with('{') {
                // JSONL line
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(trimmed) {
                    if let Some(user_id) = v.get("user_id").and_then(|val| val.as_i64()) {
                        let reason = v
                            .get("reason")
                            .and_then(|val| val.as_str())
                            .unwrap_or("Imported ban")
                            .to_string();
                        let username = v.get("username").and_then(|val| val.as_str()).map(String::from);

                        if self.repo.get_ban(fed_id, user_id).await?.is_some() {
                            duplicate_count += 1;
                        } else {
                            let ban = FederationBan {
                                id: Uuid::new_v4().to_string(),
                                federation_id: fed_id.to_string(),
                                user_id,
                                username,
                                reason,
                                created_by: requester_id,
                                created_at: now,
                                updated_at: now,
                                status: FederationBanStatus::Active,
                                version: 1,
                            };
                            let _ = self.repo.add_ban(ban).await;
                            valid_count += 1;
                        }
                    } else {
                        invalid_count += 1;
                    }
                } else {
                    invalid_count += 1;
                }
            } else {
                // CSV line
                let parts: Vec<&str> = trimmed.split(',').map(|s| s.trim_matches('"').trim()).collect();
                if let Some(first) = parts.first() {
                    if let Ok(user_id) = first.parse::<i64>() {
                        let username = parts.get(1).filter(|s| !s.is_empty()).map(|s| s.to_string());
                        let reason = parts
                            .get(2)
                            .filter(|s| !s.is_empty())
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| "Imported ban".into());

                        if self.repo.get_ban(fed_id, user_id).await?.is_some() {
                            duplicate_count += 1;
                        } else {
                            let ban = FederationBan {
                                id: Uuid::new_v4().to_string(),
                                federation_id: fed_id.to_string(),
                                user_id,
                                username,
                                reason,
                                created_by: requester_id,
                                created_at: now,
                                updated_at: now,
                                status: FederationBanStatus::Active,
                                version: 1,
                            };
                            let _ = self.repo.add_ban(ban).await;
                            valid_count += 1;
                        }
                    } else {
                        invalid_count += 1;
                    }
                } else {
                    invalid_count += 1;
                }
            }
        }

        Ok((valid_count, duplicate_count, invalid_count))
    }

    // --- Passive Presence & Enforcement Hook ---
    pub async fn process_passive_presence_and_enforce(&self, chat_id: i64, user_id: i64) -> Result<Option<EffectiveBan>> {
        let now = current_timestamp();
        self.repo.record_presence(chat_id, user_id, now).await?;

        let Some(fc) = self.repo.get_chat_federation(chat_id).await? else {
            return Ok(None);
        };

        if let Some(effective_ban) = self
            .resolver
            .resolve_effective_ban(&fc.federation_id, user_id)
            .await?
        {
            if let Some(bot) = &self.bot {
                let target_chat = teloxide::types::ChatId(chat_id);
                let target_user = teloxide::types::UserId(user_id as u64);

                if bot.ban_chat_member(target_chat, target_user).await.is_ok() {
                    if !fc.quiet_mode {
                        let fed_name = self
                            .repo
                            .get_federation(&fc.federation_id)
                            .await?
                            .map(|f| f.name)
                            .unwrap_or_else(|| fc.federation_id.clone());

                        let (source_text, reason) = match &effective_ban.source {
                            BanSource::Native => (format!("Federation <b>{}</b>", fed_name), effective_ban.reason.clone()),
                            BanSource::Subscribed { origin_fed_name, .. } => (
                                format!("Subscribed Federation <b>{}</b> (via {})", origin_fed_name, fed_name),
                                effective_ban.reason.clone(),
                            ),
                        };

                        let text = format!(
                            "🚫 <b>Federation Ban Removed User</b>\n\n\
                             User <code>{user_id}</code> was removed from this group.\n\n\
                             <b>Source:</b> {source_text}\n\
                             <b>Reason:</b> {reason}"
                        );
                        let _ = bot.send_message(target_chat, text).parse_mode(ParseMode::Html).await;
                    }
                }
            }
            return Ok(Some(effective_ban));
        }

        Ok(None)
    }

    // Internal Owner PM notification helper
    async fn notify_owner(&self, fed: &Federation, text: &str) {
        if !fed.settings.notifications_enabled {
            return;
        }
        if let Some(bot) = &self.bot {
            let owner_chat = teloxide::types::ChatId(fed.owner_user_id);
            let msg = format!("🔔 <b>Federation Notification</b>\nFederation: <b>{}</b>\n\n{}", fed.name, text);
            let _ = bot.send_message(owner_chat, msg).parse_mode(ParseMode::Html).await;
        }
    }
}
