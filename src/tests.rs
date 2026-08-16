#[cfg(test)]
mod tests {
    use crate::core::queue::{ChatQueueState, LoopMode, Track};
    use crate::ui::live_ui::SoulKingUI;

    #[test]
    fn test_queue_operations() {
        let mut q = ChatQueueState::new();

        let track1 = Track {
            id: "t1".into(),
            title: "Binks Sake".into(),
            artist: "Brook".into(),
            url: "http://example.com/1".into(),
            duration: 180,
            thumbnail: "".into(),
            requested_by: 123,
            requested_by_name: "Luffy".into(),
            source: "youtube".into(),
        };

        let track2 = Track {
            id: "t2".into(),
            title: "Soul King Live".into(),
            artist: "Brook".into(),
            url: "http://example.com/2".into(),
            duration: 240,
            thumbnail: "".into(),
            requested_by: 456,
            requested_by_name: "Zoro".into(),
            source: "deezer".into(),
        };

        q.enqueue(track1.clone());
        q.enqueue(track2.clone());

        assert_eq!(q.queue.len(), 2);

        let next = q.next_track();
        assert!(next.is_some());
        assert_eq!(next.unwrap().title, "Binks Sake");
        assert_eq!(q.queue.len(), 1);

        // Test loop mode
        q.loop_mode = LoopMode::Track;
        let repeat = q.next_track();
        assert!(repeat.is_some());
        assert_eq!(repeat.unwrap().title, "Binks Sake");
    }

    #[test]
    fn test_progress_bar() {
        let bar = SoulKingUI::build_progress_bar(60, 120, 10);
        assert!(bar.contains("01:00 / 02:00"));
        assert!(bar.contains("█████░░░░░"));
    }
}
