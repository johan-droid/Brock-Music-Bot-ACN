#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use crate::federation::models::*;
    use crate::federation::repository::{FederationRepository, MemoryFirstFederationRepository};
    use crate::federation::service::FederationService;

    #[tokio::test]
    async fn test_federation_owner_authority_only() {
        let repo = Arc::new(MemoryFirstFederationRepository::new());
        let service = FederationService::new(repo.clone(), None);

        let owner_id = 1111;
        let admin_id = 2222;
        let rando_id = 3333;

        let fed = service.create_federation("AnimeGuard".into(), owner_id, None).await.unwrap();

        // Promote fed admin (support role)
        service.add_admin(&fed.id, admin_id, owner_id).await.unwrap();

        // Owner can fban
        let (ban, _, _) = service.fban(&fed.id, 9999, Some("spammer".into()), "Spamming links".into(), owner_id)
            .await
            .expect("Owner must be allowed to fban");
        assert_eq!(ban.user_id, 9999);

        // Fed admin CANNOT fban
        let admin_res = service.fban(&fed.id, 8888, None, "Spam".into(), admin_id).await;
        assert!(admin_res.is_err(), "Federation admin MUST NOT be able to fban");

        // Random group admin/user CANNOT fban
        let rando_res = service.fban(&fed.id, 7777, None, "Spam".into(), rando_id).await;
        assert!(rando_res.is_err(), "Non-owner MUST NOT be able to fban");

        // Owner can unfban
        service.unfban(&fed.id, 9999, owner_id).await.expect("Owner must be allowed to unfban");

        // Fed admin CANNOT unfban
        let admin_unfban = service.unfban(&fed.id, 9999, admin_id).await;
        assert!(admin_unfban.is_err(), "Federation admin MUST NOT be able to unfban");
    }

    #[tokio::test]
    async fn test_multi_federation_isolation() {
        let repo = Arc::new(MemoryFirstFederationRepository::new());
        let service = FederationService::new(repo.clone(), None);

        let fed_a = service.create_federation("FedA".into(), 100, None).await.unwrap();
        let fed_b = service.create_federation("FedB".into(), 200, None).await.unwrap();

        let target_user = 555;

        // Fban target_user in FedA
        service.fban(&fed_a.id, target_user, None, "Spam".into(), 100).await.unwrap();

        // Target user is banned in FedA
        assert!(repo.get_ban(&fed_a.id, target_user).await.unwrap().is_some());

        // Target user is NOT banned in FedB
        assert!(repo.get_ban(&fed_b.id, target_user).await.unwrap().is_none());

        // FedA owner cannot manage FedB
        let err = service.fban(&fed_b.id, 666, None, "Spam".into(), 100).await;
        assert!(err.is_err());
    }

    #[tokio::test]
    async fn test_one_federation_per_chat() {
        let repo = Arc::new(MemoryFirstFederationRepository::new());
        let service = FederationService::new(repo.clone(), None);

        let fed_a = service.create_federation("FedA".into(), 100, None).await.unwrap();
        let fed_b = service.create_federation("FedB".into(), 200, None).await.unwrap();

        let chat_id = -100123456;

        service.join_chat(&fed_a.id, chat_id, 100).await.unwrap();

        // Joining a second federation should fail
        let join_err = service.join_chat(&fed_b.id, chat_id, 200).await;
        assert!(join_err.is_err(), "Group should not be able to join a second federation without leaving first");

        // Leave FedA
        service.leave_chat(chat_id, 100).await.unwrap();

        // Now can join FedB
        service.join_chat(&fed_b.id, chat_id, 200).await.unwrap();
    }

    #[tokio::test]
    async fn test_federation_subscriptions_and_dag_cycle_prevention() {
        let repo = Arc::new(MemoryFirstFederationRepository::new());
        let service = FederationService::new(repo.clone(), None);

        let fed_a = service.create_federation("FedA".into(), 100, None).await.unwrap();
        let fed_b = service.create_federation("FedB".into(), 200, None).await.unwrap();
        let fed_c = service.create_federation("FedC".into(), 300, None).await.unwrap();

        // FedA -> FedB
        service.add_subscription(&fed_a.id, &fed_b.id, 100).await.unwrap();
        // FedB -> FedC
        service.add_subscription(&fed_b.id, &fed_c.id, 200).await.unwrap();

        // Attempt FedC -> FedA (Cycle A -> B -> C -> A)
        let cycle_err = service.add_subscription(&fed_c.id, &fed_a.id, 300).await;
        assert!(cycle_err.is_err(), "Adding a subscription cycle MUST be rejected");

        // Ban user in FedC
        let target_user = 777;
        service.fban(&fed_c.id, target_user, None, "Cross-fed spam".into(), 300).await.unwrap();

        // Effective ban check on FedA should resolve target_user via C (subscribed)
        let eff_ban = service.resolver().resolve_effective_ban(&fed_a.id, target_user).await.unwrap();
        assert!(eff_ban.is_some());
        let eb = eff_ban.unwrap();
        match eb.source {
            BanSource::Subscribed { origin_fed_id, .. } => assert_eq!(origin_fed_id, fed_c.id),
            _ => panic!("Expected subscribed ban source"),
        }
    }

    #[tokio::test]
    async fn test_fban_list_import_export() {
        let repo = Arc::new(MemoryFirstFederationRepository::new());
        let service = FederationService::new(repo.clone(), None);

        let owner_id = 100;
        let fed = service.create_federation("ImportExportFed".into(), owner_id, None).await.unwrap();

        service.fban(&fed.id, 1001, Some("user1".into()), "Reason 1".into(), owner_id).await.unwrap();
        service.fban(&fed.id, 1002, Some("user2".into()), "Reason 2".into(), owner_id).await.unwrap();

        let csv = service.export_fban_list(&fed.id, "csv").await.unwrap();
        assert!(csv.contains("1001"));
        assert!(csv.contains("1002"));

        let jsonl = service.export_fban_list(&fed.id, "jsonl").await.unwrap();
        assert!(jsonl.contains("1001"));

        // Test Import
        let fed2 = service.create_federation("ImportFed2".into(), owner_id, None).await.unwrap();
        let (v, d, inv) = service.import_fban_list(&fed2.id, &csv, owner_id).await.unwrap();
        assert_eq!(v, 2);
        assert_eq!(d, 0);
        assert_eq!(inv, 0);

        assert!(repo.get_ban(&fed2.id, 1001).await.unwrap().is_some());
        assert!(repo.get_ban(&fed2.id, 1002).await.unwrap().is_some());
    }
}
