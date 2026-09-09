#[allow(clippy::module_inception)]
#[cfg(test)]
mod tests {
    use crate::commands::SoulKingUI;
    use crate::media_engine::{ChatQueueState, LoopMode, UNKNOWN_DURATION_LIMIT_SECS};
    use crate::router::{SourceKind, Track, TrackId};

    fn track(id: &str, title: &str) -> Track {
        Track {
            id: TrackId::new(id),
            title: title.into(),
            artist: Some("Brook".into()),
            url: "http://example.com".into(),
            duration_secs: 180,
            thumbnail_url: None,
            requested_by: 123,
            requested_by_name: "Luffy".into(),
            source: SourceKind::YouTube,
            external_id: None,
        }
    }

    #[test]
    fn test_queue_operations() {
        let mut q = ChatQueueState::new(100, 100);

        q.enqueue(track("t1", "Binks Sake"));
        q.enqueue(track("t2", "Soul King Live"));

        assert_eq!(q.queue.len(), 2);

        let next = q.next_track();
        assert!(next.is_some());
        assert_eq!(next.unwrap().title, "Binks Sake");
        assert_eq!(q.queue.len(), 1);
        assert_eq!(q.history.len(), 0);

        let next = q.next_track();
        assert_eq!(next.unwrap().title, "Soul King Live");
        assert_eq!(q.history.len(), 1);
        assert!(q.next_track().is_none());
        assert_eq!(q.history.len(), 2);
    }

    #[test]
    fn test_loop_mode_track_skip_advances() {
        let mut q = ChatQueueState::new(100, 100);
        q.loop_mode = LoopMode::Track;
        q.enqueue(track("t1", "Binks Sake"));
        q.enqueue(track("t2", "Soul King Live"));

        let first = q.next_track().unwrap();
        assert_eq!(first.title, "Binks Sake");

        let skipped = q.next_track().unwrap();
        assert_eq!(skipped.title, "Soul King Live");
        assert_eq!(q.history.len(), 1);
    }

    #[test]
    fn test_loop_mode_queue_rotates_without_duplication() {
        let mut q = ChatQueueState::new(100, 100);
        q.loop_mode = LoopMode::Queue;
        q.enqueue(track("t1", "Binks Sake"));
        q.enqueue(track("t2", "Soul King Live"));

        let first = q.next_track().unwrap();
        assert_eq!(first.title, "Binks Sake");
        assert!(q.history.is_empty());
        assert_eq!(q.queue.len(), 1);

        let second = q.next_track().unwrap();
        assert_eq!(second.title, "Soul King Live");

        let third = q.next_track().unwrap();
        assert_eq!(third.title, "Binks Sake");
        assert_eq!(q.queue.len(), 1);
    }

    #[test]
    fn test_prev_track() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Binks Sake"));
        q.enqueue(track("t2", "Soul King Live"));
        q.next_track();
        q.next_track();

        let prev = q.prev_track().unwrap();
        assert_eq!(prev.title, "Binks Sake");
        assert!(q.current.is_some());
    }

    #[test]
    fn test_queue_full() {
        let mut q = ChatQueueState::new(1, 100);
        assert!(q.enqueue(track("t1", "A")).is_some());
        assert!(q.enqueue(track("t2", "B")).is_none());
    }

    #[test]
    fn test_stop_reset() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Binks Sake"));
        q.next_track();
        q.is_paused = true;

        q.reset();
        assert!(q.current.is_none());
        assert!(q.queue.is_empty());
        assert!(q.history.is_empty());
        assert!(!q.is_paused);
    }

    #[test]
    fn test_default_volume() {
        let q = ChatQueueState::new(100, 60);
        assert_eq!(q.volume, 60);
    }

    #[test]
    fn test_tick_auto_advances() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Binks Sake"));
        q.next_track();
        assert!(q.current.is_some());
        for _ in 0..180 {
            q.tick();
        }
        assert!(q.current.is_none(), "track should have completed");
    }

    #[test]
    fn test_tick_paused_does_not_advance() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Binks Sake"));
        q.next_track();
        q.is_paused = true;
        for _ in 0..5 {
            q.tick();
        }
        assert!(q.current.is_some());
        assert_eq!(q.position_secs, 0);
    }

    #[test]
    fn test_tick_loop_track_replays() {
        let mut q = ChatQueueState::new(100, 100);
        q.loop_mode = LoopMode::Track;
        q.enqueue(track("t1", "Binks Sake"));
        q.next_track();
        for _ in 0..180 {
            q.tick();
        }
        assert!(
            q.current.is_some(),
            "track loop should replay the same track"
        );
        assert_eq!(q.current.as_ref().unwrap().title, "Binks Sake");
    }

    #[test]
    fn test_progress_bar() {
        let bar = SoulKingUI::build_progress_bar(60, 120, 10);
        assert!(bar.contains("01:00 / 02:00"));
        assert!(bar.contains("▓▓▓▓▓░░░░░"));
    }

    #[test]
    fn test_progress_bar_zero_duration() {
        let bar = SoulKingUI::build_progress_bar(0, 0, 10);
        assert!(bar.contains("00:00 / 00:00"));
    }

    #[test]
    fn test_tick_unknown_duration_auto_advances() {
        let mut q = ChatQueueState::new(100, 100);
        let mut unknown = track("t0", "Unknown Length");
        unknown.duration_secs = 0;
        q.current = Some(unknown);

        for _ in 0..UNKNOWN_DURATION_LIMIT_SECS {
            q.tick();
        }
        assert!(
            q.current.is_none(),
            "unknown-duration track should be capped and advanced"
        );
    }

    #[test]
    fn test_set_position_clamps_to_duration() {
        let mut q = ChatQueueState::new(100, 100);
        q.current = Some(track("t1", "Binks Sake"));
        q.set_position(60);
        assert_eq!(q.position_secs, 60);
        q.set_position(u64::MAX);
        assert_eq!(q.position_secs, 179);
        q.current.as_mut().unwrap().duration_secs = 0;
        q.set_position(5);
        assert_eq!(q.position_secs, 5);
    }

    #[test]
    fn test_clear_current_rolls_back() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Binks Sake"));
        q.next_track();
        assert!(q.current.is_some());
        q.set_position(30);

        let removed = q.clear_current();
        assert_eq!(removed.unwrap().title, "Binks Sake");
        assert!(q.current.is_none());
        assert_eq!(q.position_secs, 0);
        assert_eq!(q.queue.len(), 0);
    }

    #[test]
    fn test_skip_empty_queue_returns_error_and_preserves_queue() {
        let mut q = ChatQueueState::new(100, 100);
        assert!(q.current.is_none());
        let res = q.skip();
        assert!(res.is_err());
        assert_eq!(q.engine_state, crate::media_engine::EngineState::Idle);
    }

    #[test]
    fn test_skip_active_track_advances_to_next() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.enqueue(track("t2", "Song B"));
        q.next_track();

        assert_eq!(q.current.as_ref().unwrap().title, "Song A");
        assert_eq!(q.queue.len(), 1);

        let next = q.skip().unwrap();
        assert!(next.is_some());
        assert_eq!(next.unwrap().title, "Song B");
        assert_eq!(q.current.as_ref().unwrap().title, "Song B");
        assert_eq!(q.queue.len(), 0);
        assert_eq!(q.history.len(), 1);
        assert_eq!(q.history[0].title, "Song A");
        assert_eq!(q.engine_state, crate::media_engine::EngineState::Playing);
    }

    #[test]
    fn test_skip_final_track_settles_to_idle() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.next_track();

        let res = q.skip().unwrap();
        assert!(res.is_none());
        assert!(q.current.is_none());
        assert!(q.queue.is_empty());
        assert_eq!(q.engine_state, crate::media_engine::EngineState::Idle);
    }

    #[test]
    fn test_race_condition_transition_lock_prevents_duplicate_skip_or_eof() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.enqueue(track("t2", "Song B"));
        q.next_track();

        // 1. Begin transition to SKIPPING
        assert!(q.begin_transition(crate::media_engine::EngineState::Skipping));
        assert!(q.transition_in_progress);

        // 2. Simultaneous duplicate transition attempt (e.g. EOF + /skip race)
        assert!(!q.begin_transition(crate::media_engine::EngineState::Finished));

        // 3. End transition safely
        q.end_transition(crate::media_engine::EngineState::Playing);
        assert!(!q.transition_in_progress);
    }

    #[test]
    fn test_stop_clears_queue_and_resets_to_idle() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.enqueue(track("t2", "Song B"));
        q.next_track();

        q.reset();
        assert!(q.current.is_none());
        assert!(q.queue.is_empty());
        assert!(q.history.is_empty());
        assert_eq!(q.engine_state, crate::media_engine::EngineState::Idle);
    }

    #[test]
    fn test_play_while_playing_enqueues_without_interrupting_current() {
        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.next_track();

        // Enqueue Song B while Song A is playing
        let pos = q.enqueue(track("t2", "Song B"));
        assert_eq!(pos, Some(1));
        assert_eq!(q.current.as_ref().unwrap().title, "Song A");
        assert_eq!(q.queue.len(), 1);
        assert_eq!(q.engine_state, crate::media_engine::EngineState::Playing);
    }

    #[tokio::test]
    async fn test_db_repository_memory_first_user_settings_and_playlists() {
        use crate::db::{DbRepository, MemoryFirstDbRepository, Playlist};

        let db = MemoryFirstDbRepository::new(Some(
            "mongodb+srv://atlas-cluster.example.com/brook".into(),
        ));
        assert!(db.is_connected());

        let settings = db.get_user_settings(42).await.unwrap();
        assert_eq!(settings.user_id, 42);
        assert_eq!(settings.volume, 100);

        let mut updated = settings.clone();
        updated.volume = 80;
        db.save_user_settings(updated).await.unwrap();

        let fetched = db.get_user_settings(42).await.unwrap();
        assert_eq!(fetched.volume, 80);

        let playlist = Playlist {
            name: "Favorites".into(),
            owner_id: 42,
            track_urls: vec!["https://www.youtube.com/watch?v=x5jfluo1_Yc".into()],
        };
        db.save_playlist(playlist.clone()).await.unwrap();

        let found = db.get_playlist(42, "Favorites").await.unwrap();
        assert!(found.is_some());
        assert_eq!(found.unwrap().track_urls.len(), 1);
    }

    #[tokio::test]
    async fn test_db_repository_analytics_logging() {
        use crate::db::{DbRepository, MemoryFirstDbRepository};

        let db = MemoryFirstDbRepository::new(None);
        assert!(!db.is_connected());
        db.log_analytics("track_play", "yt:x5jfluo1_Yc")
            .await
            .unwrap();
    }

    #[test]
    fn test_voice_disconnect_preserves_queue_and_sets_waiting_for_vc() {
        use crate::media_engine::{ChatQueueState, EngineState, VoiceState};

        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.enqueue(track("t2", "Song B"));
        q.next_track();

        q.voice_state = VoiceState::Connected;
        assert_eq!(q.engine_state, EngineState::Playing);
        assert_eq!(q.playback_generation, 0);

        // Assistant leaves / VC disconnected
        q.on_voice_disconnected();

        assert_eq!(q.voice_state, VoiceState::Disconnected);
        assert_eq!(q.engine_state, EngineState::WaitingForVc);
        assert_eq!(q.playback_generation, 1);
        assert_eq!(q.queue.len(), 2);
        assert_eq!(q.queue[0].title, "Song A");
        assert_eq!(q.queue[1].title, "Song B");
    }

    #[test]
    fn test_skip_increments_playback_generation() {
        use crate::media_engine::ChatQueueState;

        let mut q = ChatQueueState::new(100, 100);
        q.enqueue(track("t1", "Song A"));
        q.next_track();
        assert_eq!(q.playback_generation, 0);

        let gen_before = q.playback_generation;
        let _ = q.skip();
        assert_eq!(q.playback_generation, gen_before + 1);
    }

    #[tokio::test]
    async fn test_multi_track_queue_transition_does_not_clear_queue() {
        use crate::media_engine::{
            InMemoryQueueRepository, MediaEngine, MockPlaybackTransport, TransitionReason,
        };
        use std::sync::Arc;

        let repo = Arc::new(InMemoryQueueRepository::new(100, 100));
        let transport = Arc::new(MockPlaybackTransport::new());
        let me = MediaEngine::new(repo.clone(), transport);

        let chat_id = 999;
        me.enqueue_and_play(chat_id, track("t1", "Track A"))
            .await
            .unwrap();
        me.enqueue_and_play(chat_id, track("t2", "Track B"))
            .await
            .unwrap();
        me.enqueue_and_play(chat_id, track("t3", "Track C"))
            .await
            .unwrap();

        let st = me.state(chat_id).await.unwrap();
        assert_eq!(st.current.as_ref().unwrap().title, "Track A");
        assert_eq!(st.queue_len, 2);

        // Advance Track A (EOF) -> Track B should play, Track C in queue
        let b = me
            .advance_to_next_track(chat_id, TransitionReason::Eof)
            .await
            .unwrap();
        assert_eq!(b.as_ref().unwrap().title, "Track B");
        let st2 = me.state(chat_id).await.unwrap();
        assert_eq!(st2.current.as_ref().unwrap().title, "Track B");
        assert_eq!(st2.queue_len, 1);
        assert_eq!(st2.queue[0].title, "Track C");

        // Advance Track B (EOF) -> Track C should play, queue empty
        let c = me
            .advance_to_next_track(chat_id, TransitionReason::Eof)
            .await
            .unwrap();
        assert_eq!(c.as_ref().unwrap().title, "Track C");
        let st3 = me.state(chat_id).await.unwrap();
        assert_eq!(st3.current.as_ref().unwrap().title, "Track C");
        assert_eq!(st3.queue_len, 0);

        // Advance Track C (EOF) -> Idle
        let done = me
            .advance_to_next_track(chat_id, TransitionReason::Eof)
            .await
            .unwrap();
        assert!(done.is_none());
        let st4 = me.state(chat_id).await.unwrap();
        assert!(st4.current.is_none());
        assert_eq!(st4.engine_state, crate::media_engine::EngineState::Idle);
    }

    #[tokio::test]
    async fn test_duplicate_title_requests_have_unique_track_ids() {
        use crate::media_engine::{
            InMemoryQueueRepository, MediaEngine, MockPlaybackTransport, TransitionReason,
        };
        use std::sync::Arc;

        let repo = Arc::new(InMemoryQueueRepository::new(100, 100));
        let transport = Arc::new(MockPlaybackTransport::new());
        let me = MediaEngine::new(repo.clone(), transport);

        let chat_id = 888;
        me.enqueue_and_play(chat_id, track("same_id", "Believer"))
            .await
            .unwrap();
        me.enqueue_and_play(chat_id, track("same_id", "Believer"))
            .await
            .unwrap();

        let st = me.state(chat_id).await.unwrap();
        assert_eq!(st.current.as_ref().unwrap().title, "Believer");
        assert_eq!(st.queue_len, 1);
        assert_ne!(st.current.as_ref().unwrap().id, st.queue[0].id);

        let next = me
            .advance_to_next_track(chat_id, TransitionReason::Eof)
            .await
            .unwrap();
        assert_eq!(next.as_ref().unwrap().title, "Believer");
        let st2 = me.state(chat_id).await.unwrap();
        assert_eq!(st2.queue_len, 0);
    }

    #[test]
    fn test_assert_invariants_self_heals_playing_state_without_track() {
        use crate::media_engine::{ChatQueueState, EngineState};

        let mut q = ChatQueueState::new(100, 100);
        q.engine_state = EngineState::Playing;
        q.current = None;

        q.assert_invariants();

        assert_eq!(q.engine_state, EngineState::Idle);
    }

    #[test]
    fn test_prune_inactive_sessions_evicts_idle_chats() {
        use crate::media_engine::InMemoryQueueRepository;
        use std::time::Duration;

        let repo = InMemoryQueueRepository::new(100, 100);
        let _ = repo.get_or_create(111); // Empty idle chat
        let _active = repo.get_or_create(222);
        _active.blocking_write().enqueue(track("t1", "Active Song"));

        assert_eq!(repo.active_chats().len(), 2);

        repo.prune_inactive_sessions(Duration::from_secs(1800));

        let remaining = repo.active_chats();
        assert_eq!(remaining.len(), 1);
        assert_eq!(remaining[0], 222);
    }

    #[tokio::test]
    async fn test_authorization_manager_permissions() {
        use crate::commands::{AuthorizationManager, BotCommand};
        use crate::media_engine::{InMemoryQueueRepository, MediaEngine, MockPlaybackTransport};
        use std::sync::Arc;

        let repo = Arc::new(InMemoryQueueRepository::new(100, 100));
        let transport = Arc::new(MockPlaybackTransport::new());
        let me = MediaEngine::new(repo.clone(), transport);

        let chat_id = 777;
        let user_a = 123;
        let user_b = 200;

        me.enqueue_and_play(chat_id, track("t1", "User A Song"))
            .await
            .unwrap();
        me.repo
            .set_session_owner(chat_id, user_a, "User A")
            .await
            .unwrap();

        let st = me.state(chat_id).await.unwrap();
        assert_eq!(st.owner_user_id, Some(user_a));

        // Public commands authorized for anyone
        assert!(AuthorizationManager::authorize(
            &BotCommand::Help,
            user_b,
            chat_id,
            &st,
            None,
            false
        )
        .is_ok());
        assert!(AuthorizationManager::authorize(
            &BotCommand::Queue,
            user_b,
            chat_id,
            &st,
            None,
            false
        )
        .is_ok());

        // Session Controller commands authorized for User A (Owner) and Admins
        assert!(AuthorizationManager::authorize(
            &BotCommand::Skip,
            user_a,
            chat_id,
            &st,
            None,
            false
        )
        .is_ok());
        assert!(AuthorizationManager::authorize(
            &BotCommand::Skip,
            user_b,
            chat_id,
            &st,
            None,
            true
        )
        .is_ok());

        // Session Controller commands DENIED for User B (Non-owner, non-admin)
        let denied =
            AuthorizationManager::authorize(&BotCommand::Skip, user_b, chat_id, &st, None, false);
        assert!(denied.is_err());
    }

    #[tokio::test]
    async fn test_playback_interruption_protection_enqueues_safely() {
        use crate::commands::AuthorizationManager;
        use crate::media_engine::{InMemoryQueueRepository, MediaEngine, MockPlaybackTransport};
        use std::sync::Arc;

        let repo = Arc::new(InMemoryQueueRepository::new(100, 100));
        let transport = Arc::new(MockPlaybackTransport::new());
        let me = MediaEngine::new(repo.clone(), transport);

        let chat_id = 666;
        let user_a = 101;
        let user_b = 202;

        let track1 = Track {
            id: crate::router::TrackId::new("t1"),
            title: "User A Track".into(),
            artist: None,
            url: "https://example.com/1".into(),
            duration_secs: 180,
            thumbnail_url: None,
            requested_by: user_a,
            requested_by_name: "User A".into(),
            source: crate::router::SourceKind::DirectUrl,
            external_id: None,
        };

        let track2 = Track {
            id: crate::router::TrackId::new("t2"),
            title: "User B Track".into(),
            artist: None,
            url: "https://example.com/2".into(),
            duration_secs: 200,
            thumbnail_url: None,
            requested_by: user_b,
            requested_by_name: "User B".into(),
            source: crate::router::SourceKind::DirectUrl,
            external_id: None,
        };

        // User A starts playback
        me.enqueue_and_play(chat_id, track1).await.unwrap();
        let st1 = me.state(chat_id).await.unwrap();
        assert_eq!(st1.current.as_ref().unwrap().title, "User A Track");
        assert_eq!(st1.owner_user_id, Some(user_a));

        // User B attempts to skip (Unauthorized) -> Denied
        let denied = AuthorizationManager::authorize(
            &crate::commands::BotCommand::Skip,
            user_b,
            chat_id,
            &st1,
            None,
            false,
        );
        assert!(denied.is_err());

        // User B attempts /play Track 2 -> Safely enqueued at position 1 without interrupting User A
        let pos = me.enqueue_and_play(chat_id, track2).await.unwrap();
        assert_eq!(pos, Some(1));

        let st2 = me.state(chat_id).await.unwrap();
        assert_eq!(st2.current.as_ref().unwrap().title, "User A Track"); // Still User A's track!
        assert_eq!(st2.queue_len, 1);
        assert_eq!(st2.queue[0].title, "User B Track");
    }
}
