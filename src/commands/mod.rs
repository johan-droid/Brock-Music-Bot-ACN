use std::sync::Arc;
use teloxide::{
    prelude::*,
    utils::command::BotCommands,
};
use crate::{
    cache::AppCache,
    config::Config,
    core::{call_manager::CallManager, music_backend::MusicBackend, queue::{LoopMode, QueueManager}},
    db::Database,
    ui::live_ui::SoulKingUI,
};

#[derive(BotCommands, Clone, Debug)]
#[command(rename_rule = "lowercase", description = "🎵 Soul King Brook Music Bot Commands:")]
pub enum Command {
    #[command(description = "Show the full command setlist")]
    Help,
    #[command(description = "Check bot latency & responsiveness")]
    Ping,
    #[command(description = "Play a song in the voice chat")]
    Play(String),
    #[command(description = "Pause the current performance")]
    Pause,
    #[command(description = "Resume paused playback")]
    Resume,
    #[command(description = "Skip to the next track")]
    Skip,
    #[command(description = "Play the previous track")]
    Prev,
    #[command(description = "Replay the current track")]
    Replay,
    #[command(description = "Stop playback and clear stage")]
    Stop,
    #[command(description = "View the current setlist / queue")]
    Queue,
    #[command(description = "Show the currently performing track")]
    Now,
    #[command(description = "Randomize the setlist queue")]
    Shuffle,
    #[command(description = "Toggle loop mode (off, track, queue)")]
    Loop(String),
    #[command(description = "Set playback volume (0-200)")]
    Volume(String),
    #[command(description = "Discover songs by vibe or mood")]
    Vibe(String),
    #[command(description = "Promote user to Sudo (Owner only)")]
    AddSudo(String),
    #[command(description = "Show bot statistics")]
    Stats,
}

pub struct AppState {
    pub config: Config,
    pub db: Database,
    pub cache: AppCache,
    pub queues: QueueManager,
    pub calls: CallManager,
    pub music_backend: MusicBackend,
}

pub async fn handle_command(
    bot: Bot,
    msg: Message,
    cmd: Command,
    state: Arc<AppState>,
) -> ResponseResult<()> {
    let chat_id = msg.chat.id.0;
    let user = msg.from.as_ref();
    let user_id = user.map(|u| u.id.0 as i64).unwrap_or(0);
    let user_name = user.map(|u| u.first_name.clone()).unwrap_or_else(|| "Member".into());

    match cmd {
        Command::Help => {
            let help_text = Command::descriptions().to_string();
            bot.send_message(msg.chat.id, format!("☠️ **SOUL KING COMMAND MENU** ☠️\n\n{}", help_text))
                .parse_mode(teloxide::types::ParseMode::MarkdownV2)
                .await?;
        }

        Command::Ping => {
            let start = std::time::Instant::now();
            let sent = bot.send_message(msg.chat.id, "🪕 Tuning instruments...").await?;
            let elapsed = start.elapsed().as_millis();
            bot.edit_message_text(
                msg.chat.id,
                sent.id,
                format!("⚡ **Yohohoho! Stage latency:** `{} ms`", elapsed),
            )
            .await?;
        }

        Command::Play(query) => {
            if query.trim().is_empty() {
                bot.send_message(msg.chat.id, "⚠️ Please specify a song name or URL! Example: `/play Binks Sake`").await?;
                return Ok(());
            }

            let search_msg = bot.send_message(msg.chat.id, format!("🔎 *Soul King searching for:* `{}`...", query)).await?;

            match state.music_backend.search_track(&query, user_id, &user_name).await {
                Ok(track) => {
                    let queue_lock = state.queues.get_or_create(chat_id).await;
                    let mut q = queue_lock.write().await;
                    
                    if q.current.is_none() {
                        q.current = Some(track.clone());
                        let text = SoulKingUI::format_now_playing(&track, 0, &q.loop_mode, false);
                        let markup = SoulKingUI::build_control_buttons(false, &q.loop_mode);
                        bot.edit_message_text(msg.chat.id, search_msg.id, text)
                            .reply_markup(markup)
                            .await?;
                    } else {
                        let pos = q.enqueue(track.clone());
                        bot.edit_message_text(
                            msg.chat.id,
                            search_msg.id,
                            format!("🎶 **Added to Setlist (Position #{}):** `{}`", pos, track.title),
                        )
                        .await?;
                    }
                }
                Err(err) => {
                    bot.edit_message_text(msg.chat.id, search_msg.id, format!("❌ Could not find track: {}", err)).await?;
                }
            }
        }

        Command::Pause => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            q.is_paused = true;
            bot.send_message(msg.chat.id, "⏸️ **Performance Paused!** Use `/resume` to continue.").await?;
        }

        Command::Resume => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            q.is_paused = false;
            bot.send_message(msg.chat.id, "▶️ **Performance Resumed!**").await?;
        }

        Command::Skip => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            if let Some(next) = q.next_track() {
                bot.send_message(msg.chat.id, format!("⏭️ **Skipped!** Now performing: `{}`", next.title)).await?;
            } else {
                bot.send_message(msg.chat.id, "⏹️ **End of setlist!** Stage is now clear.").await?;
            }
        }

        Command::Prev => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            if let Some(prev) = q.prev_track() {
                bot.send_message(msg.chat.id, format!("⏮️ **Replaying Previous:** `{}`", prev.title)).await?;
            } else {
                bot.send_message(msg.chat.id, "⚠️ No previous track in history.").await?;
            }
        }

        Command::Replay => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let q = queue_lock.read().await;
            if let Some(curr) = &q.current {
                bot.send_message(msg.chat.id, format!("🔄 **Restarting Track:** `{}`", curr.title)).await?;
            } else {
                bot.send_message(msg.chat.id, "⚠️ Nothing is currently playing.").await?;
            }
        }

        Command::Stop => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            q.clear();
            q.current = None;
            bot.send_message(msg.chat.id, "⏹️ **Concert Ended!** Stage cleared and queue reset.").await?;
        }

        Command::Queue => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let q = queue_lock.read().await;

            let mut out = String::from("📋 **CURRENT CONCERT SETLIST** 📋\n\n");
            if let Some(curr) = &q.current {
                out.push_str(&format!("▶️ **Now Playing:** `{}` (requested by {})\n\n", curr.title, curr.requested_by_name));
            } else {
                out.push_str("⏸️ Stage is idle.\n\n");
            }

            if q.queue.is_empty() {
                out.push_str("*(No upcoming tracks queued)*");
            } else {
                out.push_str("**Upcoming Tracks:**\n");
                for (i, t) in q.queue.iter().enumerate().take(10) {
                    out.push_str(&format!("{}. `{}` - {}\n", i + 1, t.title, t.requested_by_name));
                }
            }

            bot.send_message(msg.chat.id, out).await?;
        }

        Command::Now => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let q = queue_lock.read().await;
            if let Some(curr) = &q.current {
                let text = SoulKingUI::format_now_playing(curr, 45, &q.loop_mode, q.is_paused);
                let markup = SoulKingUI::build_control_buttons(q.is_paused, &q.loop_mode);
                bot.send_message(msg.chat.id, text).reply_markup(markup).await?;
            } else {
                bot.send_message(msg.chat.id, "⏸️ Nothing performing live on stage right now.").await?;
            }
        }

        Command::Shuffle => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            q.shuffle();
            bot.send_message(msg.chat.id, "🔀 **Setlist Shuffled!** New track order ready.").await?;
        }

        Command::Loop(mode) => {
            let queue_lock = state.queues.get_or_create(chat_id).await;
            let mut q = queue_lock.write().await;
            match mode.to_lowercase().as_str() {
                "track" => q.loop_mode = LoopMode::Track,
                "queue" | "setlist" => q.loop_mode = LoopMode::Queue,
                _ => q.loop_mode = LoopMode::Off,
            }
            bot.send_message(msg.chat.id, format!("🔄 **Loop Mode set to:** `{:?}`", q.loop_mode)).await?;
        }

        Command::Volume(vol_str) => {
            if let Ok(vol) = vol_str.parse::<u32>() {
                let vol = vol.min(200);
                let queue_lock = state.queues.get_or_create(chat_id).await;
                let mut q = queue_lock.write().await;
                q.volume = vol;
                bot.send_message(msg.chat.id, format!("🔊 **Volume set to:** `{}%`", vol)).await?;
            } else {
                bot.send_message(msg.chat.id, "⚠️ Please specify volume from 0 to 200.").await?;
            }
        }

        Command::Vibe(mood) => {
            bot.send_message(msg.chat.id, format!("🎸 **Brook's Vibe Selection for [{}]**: Binks' Sake, Soul Concert Live!", mood)).await?;
        }

        Command::AddSudo(target) => {
            if state.config.owner_id == Some(user_id) {
                bot.send_message(msg.chat.id, format!("✅ Promoted `{}` to Sudo user!", target)).await?;
            } else {
                bot.send_message(msg.chat.id, "⛔ Sudo permissions required.").await?;
            }
        }

        Command::Stats => {
            let active = state.queues.active_chats().len();
            bot.send_message(
                msg.chat.id,
                format!(
                    "📊 **BROOK MUSIC BOT STATS** 📊\n\n\
                     • **Active Voice Chats:** `{}`\n\
                     • **Engine:** `Pure Rust (Tokio/Teloxide/Axum)`\n\
                     • **Microservice Health:** `{}`",
                    active,
                    if state.music_backend.check_health().await { "Online ✅" } else { "Offline ⚠️" }
                ),
            )
            .await?;
        }
    }

    Ok(())
}
