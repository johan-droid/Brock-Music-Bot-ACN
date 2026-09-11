use std::collections::HashSet;
use std::sync::Arc;
use futures::future::BoxFuture;
use futures::FutureExt;

use crate::error::Result;
use crate::federation::models::*;
use crate::federation::repository::FederationRepository;

pub struct FederationBanResolver {
    repo: Arc<dyn FederationRepository>,
}

impl FederationBanResolver {
    pub fn new(repo: Arc<dyn FederationRepository>) -> Self {
        Self { repo }
    }

    pub async fn resolve_effective_ban(
        &self,
        fed_id: &str,
        user_id: i64,
    ) -> Result<Option<EffectiveBan>> {
        let mut visited = HashSet::new();
        self.resolve_recursive(fed_id, user_id, &mut visited, true)
            .await
    }

    fn resolve_recursive<'a>(
        &'a self,
        current_fed_id: &'a str,
        user_id: i64,
        visited: &'a mut HashSet<String>,
        is_native: bool,
    ) -> BoxFuture<'a, Result<Option<EffectiveBan>>> {
        async move {
            if !visited.insert(current_fed_id.to_string()) {
                return Ok(None);
            }

            if let Some(ban) = self.repo.get_ban(current_fed_id, user_id).await? {
                if ban.status == FederationBanStatus::Active {
                    let source = if is_native {
                        BanSource::Native
                    } else {
                        let fed_name = self
                            .repo
                            .get_federation(current_fed_id)
                            .await?
                            .map(|f| f.name)
                            .unwrap_or_else(|| current_fed_id.to_string());

                        BanSource::Subscribed {
                            origin_fed_id: current_fed_id.to_string(),
                            origin_fed_name: fed_name,
                        }
                    };

                    return Ok(Some(EffectiveBan {
                        user_id,
                        federation_id: current_fed_id.to_string(),
                        source,
                        reason: ban.reason,
                        banned_at: ban.created_at,
                    }));
                }
            }

            let subs = self.repo.list_subscriptions(current_fed_id).await?;
            for sub in subs {
                if let Some(eff_ban) = self
                    .resolve_recursive(&sub.target_fed_id, user_id, visited, false)
                    .await?
                {
                    return Ok(Some(eff_ban));
                }
            }

            Ok(None)
        }
        .boxed()
    }

    pub async fn check_subscription_cycle(
        &self,
        source_fed_id: &str,
        target_fed_id: &str,
    ) -> Result<bool> {
        if source_fed_id == target_fed_id {
            return Ok(true);
        }
        let mut visited = HashSet::new();
        self.detect_path(target_fed_id, source_fed_id, &mut visited)
            .await
    }

    fn detect_path<'a>(
        &'a self,
        start_fed_id: &'a str,
        target_fed_id: &'a str,
        visited: &'a mut HashSet<String>,
    ) -> BoxFuture<'a, Result<bool>> {
        async move {
            if start_fed_id == target_fed_id {
                return Ok(true);
            }
            if !visited.insert(start_fed_id.to_string()) {
                return Ok(false);
            }

            let subs = self.repo.list_subscriptions(start_fed_id).await?;
            for sub in subs {
                if self.detect_path(&sub.target_fed_id, target_fed_id, visited).await? {
                    return Ok(true);
                }
            }

            Ok(false)
        }
        .boxed()
    }
}
