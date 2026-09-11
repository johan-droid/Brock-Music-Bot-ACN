use std::sync::Arc;
use teloxide::prelude::*;
use teloxide::types::ParseMode;
use tracing::{error, info};

use crate::error::Result;
use crate::federation::models::*;
use crate::federation::repository::FederationRepository;

pub struct EnforcementWorker {
    repo: Arc<dyn FederationRepository>,
    bot: Option<Bot>,
}

impl EnforcementWorker {
    pub fn new(repo: Arc<dyn FederationRepository>, bot: Option<Bot>) -> Self {
        Self { repo, bot }
    }

    pub async fn process_pending_jobs(&self) -> Result<()> {
        let pending = self.repo.get_pending_jobs().await?;
        for job in pending {
            self.execute_job(job).await?;
        }
        Ok(())
    }

    pub async fn execute_job(&self, job: EnforcementJob) -> Result<()> {
        let current_ban = self.repo.get_ban(&job.federation_id, job.user_id).await?;
        match current_ban {
            Some(ban) if ban.status == FederationBanStatus::Active && ban.version == job.expected_version => {}
            _ => {
                info!(job_id = %job.job_id, "Aborting stale enforcement job");
                self.repo
                    .update_job_status(&job.job_id, EnforcementJobStatus::Stale, Some("Stale operation version or ban inactive".into()))
                    .await?;
                return Ok(());
            }
        }

        let Some(bot) = &self.bot else {
            self.repo
                .update_job_status(&job.job_id, EnforcementJobStatus::Skipped, Some("No active Telegram bot instance".into()))
                .await?;
            return Ok(());
        };

        let chat_id = teloxide::types::ChatId(job.target_chat_id);
        let user_id = teloxide::types::UserId(job.user_id as u64);

        match bot.ban_chat_member(chat_id, user_id).await {
            Ok(_) => {
                self.repo
                    .update_job_status(&job.job_id, EnforcementJobStatus::Enforced, None)
                    .await?;

                if !job.quiet_mode {
                    let fed_name = self
                        .repo
                        .get_federation(&job.federation_id)
                        .await?
                        .map(|f| f.name)
                        .unwrap_or_else(|| job.federation_id.clone());

                    let text = format!(
                        "🚫 <b>Federation Ban Enforcement</b>\n\n\
                         User <code>{}</code> has been removed from this group.\n\n\
                         <b>Federation:</b> {}\n\
                         <b>Reason:</b> {}",
                        job.user_id,
                        fed_name,
                        job.reason
                    );
                    let _ = bot.send_message(chat_id, text).parse_mode(ParseMode::Html).await;
                }
            }
            Err(e) => {
                let err_str = e.to_string();
                error!(job_id = %job.job_id, error = %err_str, "Failed to enforce federation ban");
                self.repo
                    .update_job_status(&job.job_id, EnforcementJobStatus::Failed, Some(err_str))
                    .await?;
            }
        }

        Ok(())
    }
}
