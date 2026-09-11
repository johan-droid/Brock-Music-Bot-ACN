use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FederationStatus {
    Active,
    Deleted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FederationVisibility {
    Public,
    Private,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FederationSettings {
    pub require_reason: bool,
    pub notifications_enabled: bool,
    pub logging_enabled: bool,
    pub quiet_mode_default: bool,
}

impl Default for FederationSettings {
    fn default() -> Self {
        Self {
            require_reason: false,
            notifications_enabled: true,
            logging_enabled: true,
            quiet_mode_default: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Federation {
    pub id: String,
    pub name: String,
    pub description: Option<String>,
    pub owner_user_id: i64,
    pub created_at: i64,
    pub updated_at: i64,
    pub status: FederationStatus,
    pub visibility: FederationVisibility,
    pub settings: FederationSettings,
    pub log_chat_id: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FederationChat {
    pub federation_id: String,
    pub chat_id: i64,
    pub joined_at: i64,
    pub joined_by: i64,
    pub status: String, // "active" or "left"
    pub quiet_mode: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FederationBanStatus {
    Active,
    Removed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FederationBan {
    pub id: String,
    pub federation_id: String,
    pub user_id: i64,
    pub username: Option<String>,
    pub reason: String,
    pub created_by: i64,
    pub created_at: i64,
    pub updated_at: i64,
    pub status: FederationBanStatus,
    pub version: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FederationSubscription {
    pub source_fed_id: String, // Subscriber federation
    pub target_fed_id: String, // Subscribed-to federation
    pub created_at: i64,
    pub created_by: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FederationAdmin {
    pub federation_id: String,
    pub user_id: i64,
    pub promoted_at: i64,
    pub promoted_by: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatUserPresence {
    pub chat_id: i64,
    pub user_id: i64,
    pub first_seen_at: i64,
    pub last_seen_at: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FederationEventType {
    FedCreated,
    FedDeleted,
    ChatJoined,
    ChatLeft,
    FedbanCreated,
    FedbanRemoved,
    FedbanEnforced,
    FedbanFailed,
    SubfedAdded,
    SubfedRemoved,
    FedAdminPromoted,
    FedAdminDemoted,
    FedSettingsChanged,
    FedLogChanged,
}

impl FederationEventType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::FedCreated => "FED_CREATED",
            Self::FedDeleted => "FED_DELETED",
            Self::ChatJoined => "CHAT_JOINED",
            Self::ChatLeft => "CHAT_LEFT",
            Self::FedbanCreated => "FEDBAN_CREATED",
            Self::FedbanRemoved => "FEDBAN_REMOVED",
            Self::FedbanEnforced => "FEDBAN_ENFORCED",
            Self::FedbanFailed => "FEDBAN_FAILED",
            Self::SubfedAdded => "SUBFED_ADDED",
            Self::SubfedRemoved => "SUBFED_REMOVED",
            Self::FedAdminPromoted => "FED_ADMIN_PROMOTED",
            Self::FedAdminDemoted => "FED_ADMIN_DEMOTED",
            Self::FedSettingsChanged => "FED_SETTINGS_CHANGED",
            Self::FedLogChanged => "FED_LOG_CHANGED",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FederationEvent {
    pub id: String,
    pub federation_id: String,
    pub event_type: FederationEventType,
    pub actor_user_id: i64,
    pub target_user_id: Option<i64>,
    pub target_chat_id: Option<i64>,
    pub metadata: Option<String>,
    pub created_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BanSource {
    Native,
    Subscribed {
        origin_fed_id: String,
        origin_fed_name: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EffectiveBan {
    pub user_id: i64,
    pub federation_id: String,
    pub source: BanSource,
    pub reason: String,
    pub banned_at: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EnforcementJobStatus {
    Pending,
    Enforced,
    Failed,
    Skipped,
    Stale,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnforcementJob {
    pub job_id: String,
    pub federation_id: String,
    pub user_id: i64,
    pub target_chat_id: i64,
    pub reason: String,
    pub quiet_mode: bool,
    pub expected_version: u64,
    pub created_at: i64,
    pub status: EnforcementJobStatus,
    pub error_message: Option<String>,
}
