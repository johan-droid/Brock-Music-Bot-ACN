use teloxide::types::{InlineKeyboardButton, InlineKeyboardMarkup};
use crate::core::queue::{LoopMode, Track};

pub struct SoulKingUI;

impl SoulKingUI {
    pub fn build_progress_bar(current_secs: u64, total_secs: u64, length: usize) -> String {
        if total_secs == 0 {
            return format!("[{}] 00:00 / 00:00", "░".repeat(length));
        }

        let progress = (current_secs as f64 / total_secs as f64).min(1.0);
        let filled = (progress * length as f64).round() as usize;
        let empty = length.saturating_sub(filled);

        let cur_fmt = format!("{:02}:{:02}", current_secs / 60, current_secs % 60);
        let tot_fmt = format!("{:02}:{:02}", total_secs / 60, total_secs % 60);

        format!("[{}{}] {} / {}", "█".repeat(filled), "░".repeat(empty), cur_fmt, tot_fmt)
    }

    pub fn format_now_playing(track: &Track, current_secs: u64, loop_mode: &LoopMode, is_paused: bool) -> String {
        let status = if is_paused { "⏸️ PAUSED" } else { "🎸 PERFORMING LIVE" };
        let loop_status = match loop_mode {
            LoopMode::Off => "Off ➡️",
            LoopMode::Track => "Repeat Track 🔂",
            LoopMode::Queue => "Repeat Setlist 🔁",
        };

        let progress = Self::build_progress_bar(current_secs, track.duration, 14);

        format!(
            "☠️ **SOUL KING CONCERT STAGE** ☠️\n\n\
             🎵 **Track:** {}\n\
             🎙️ **Artist:** {}\n\
             👤 **Requested by:** {}\n\
             📻 **Source:** {}\n\
             🔁 **Loop Mode:** {}\n\
             ⚡ **Status:** {}\n\n\
             `{}`\n\n\
             *Yohohoho! Feel the music in your bones!*",
            track.title,
            track.artist,
            track.requested_by_name,
            track.source.to_uppercase(),
            loop_status,
            status,
            progress
        )
    }

    pub fn build_control_buttons(is_paused: bool, loop_mode: &LoopMode) -> InlineKeyboardMarkup {
        let pause_resume_label = if is_paused { "▶️ Resume" } else { "⏸️ Pause" };
        let loop_label = match loop_mode {
            LoopMode::Off => "🔄 Loop: Off",
            LoopMode::Track => "🔂 Loop: Track",
            LoopMode::Queue => "🔁 Loop: Setlist",
        };

        let row1 = vec![
            InlineKeyboardButton::callback(pause_resume_label, "cb_toggle_pause"),
            InlineKeyboardButton::callback("⏭️ Skip", "cb_skip"),
            InlineKeyboardButton::callback("⏹️ Stop", "cb_stop"),
        ];

        let row2 = vec![
            InlineKeyboardButton::callback(loop_label, "cb_toggle_loop"),
            InlineKeyboardButton::callback("🔀 Shuffle", "cb_shuffle"),
            InlineKeyboardButton::callback("📋 Queue", "cb_queue"),
        ];

        let row3 = vec![
            InlineKeyboardButton::callback("🔉 Vol -", "cb_vol_down"),
            InlineKeyboardButton::callback("🔊 Vol +", "cb_vol_up"),
            InlineKeyboardButton::callback("🎛️ Effects", "cb_effects"),
        ];

        InlineKeyboardMarkup::new(vec![row1, row2, row3])
    }
}
