use std::sync::Arc;
use teloxide::prelude::*;
use teloxide::types::{InlineKeyboardButton, InlineKeyboardMarkup, Message, ParseMode};
use teloxide::utils::command::BotCommands;

use crate::ai::AiReceiver;
use crate::media_engine::{LoopMode, MediaEngine};
use crate::router::{MusicRouter, Platform, Route, SourceAdapter, Track};

pub fn build_live_router(
    lazy: &crate::LazyProviders,
    config: &crate::config::Config,
) -> MusicRouter {
    let youtube = lazy.youtube();
    let spotify = lazy.spotify();
    let apple = lazy.apple();
    let soundcloud = lazy.soundcloud();
    let direct = lazy.direct.as_ref().unwrap().clone();

    let mut routes = vec![Route::new(Platform::DirectUrl, direct)];
    if config.youtube_enabled {
        routes.push(Route::new(Platform::YouTube, youtube.clone()));
    }
    if config.spotify_client_id.is_some() && config.spotify_client_secret.is_some() {
        routes.push(Route::new(Platform::Spotify, spotify.clone()));
    }
    routes.push(Route::new(Platform::AppleMusic, apple.clone()));
    if config.soundcloud_client_id.is_some() {
        routes.push(Route::new(Platform::SoundCloud, soundcloud.clone()));
    }

    let mut search_chain: Vec<Arc<dyn SourceAdapter>> = Vec::new();
    if config.youtube_enabled {
        search_chain.push(youtube);
    }
    if config.spotify_client_id.is_some() && config.spotify_client_secret.is_some() {
        search_chain.push(spotify);
    }
    search_chain.push(apple);
    if config.soundcloud_client_id.is_some() {
        search_chain.push(soundcloud);
    }

    MusicRouter::new(routes, search_chain, config)
}

pub fn escape_html(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

pub fn format_time(secs: u64) -> String {
    format!("{:02}:{:02}", secs / 60, secs % 60)
}

pub struct SoulKingUI;

impl SoulKingUI {
    pub fn build_progress_bar(current_secs: u64, total_secs: u64, length: usize) -> String {
        if total_secs == 0 {
            return format!(
                "[{}{}] 00:00 / 00:00",
                "▓".repeat(length / 2),
                "░".repeat(length - length / 2)
            );
        }

        let progress = (current_secs as f64 / total_secs as f64).min(1.0);
        let filled = (progress * length as f64).round() as usize;
        let empty = length.saturating_sub(filled);

        format!(
            "▶ [{}{}] {} / {}",
            "▓".repeat(filled),
            "░".repeat(empty),
            format_time(current_secs),
            format_time(total_secs)
        )
    }

    pub fn format_now_playing(
        track: &Track,
        current_secs: u64,
        is_paused: bool,
        loop_mode: &LoopMode,
        voice_state: crate::media_engine::VoiceState,
        queue: &[Track],
    ) -> String {
        let status = if is_paused {
            "⏸️ PAUSED"
        } else {
            "🎸 PERFORMING LIVE"
        };
        let loop_status = match loop_mode {
            LoopMode::Off => "Off ➡️",
            LoopMode::Track => "Repeat Track 🔂",
            LoopMode::Queue => "Repeat Setlist 🔁",
        };

        let progress = Self::build_progress_bar(current_secs, track.duration_secs, 14);
        let artist_str = track.artist.as_deref().unwrap_or("Unknown Artist");

        let mut queue_preview = String::new();
        if !queue.is_empty() {
            queue_preview.push_str("\n\n<b>📜 UP NEXT IN QUEUE:</b>\n");
            for (i, t) in queue.iter().take(3).enumerate() {
                queue_preview.push_str(&format!(
                    "  {}. <code>{}</code>\n",
                    i + 1,
                    escape_html(&t.title)
                ));
            }
            if queue.len() > 3 {
                queue_preview.push_str(&format!("  <i>...and {} more</i>\n", queue.len() - 3));
            }
        }

        format!(
            "☠️ <b>SOUL KING CONCERT STAGE</b> ☠️\n\
             ──────────────────────────────\n\
             <blockquote>\
             🎵 <b>Track:</b> <code>{title}</code>\n\
             🎙️ <b>Artist:</b> {artist}\n\
             👑 <b>Requested by:</b> {requested}\n\
             📻 <b>Source:</b> {source:?}\n\
             🔊 <b>Voice Chat:</b> {voice_state}\n\
             ⏱️ <b>Time:</b> <code>{cur} / {tot}</code>\n\
             🔁 <b>Loop:</b> {loop_status}   ⚡ <b>Status:</b> {status}\n\n\
             {progress}\
             {queue_preview}\
             </blockquote>\n\
             <i>🎻 Yohohoho! Binks' Sake! Feel it in your bones! 🎻</i>",
            title = escape_html(&track.title),
            artist = escape_html(artist_str),
            requested = escape_html(&track.requested_by_name),
            source = track.source,
            voice_state = voice_state.display_text(),
            cur = format_time(current_secs),
            tot = format_time(track.duration_secs),
            loop_status = loop_status,
            status = status,
            progress = progress,
            queue_preview = queue_preview,
        )
    }

    pub fn format_enqueued(track: &Track, pos: usize) -> String {
        format!(
            "🎵 <b>Added to Setlist (Position #{pos})!</b>\n\
             ──────────────────────────────\n\
             <blockquote>\
             <code>{title}</code> — {artist}\n\
             Requested by: {requested}\
             </blockquote>",
            pos = pos,
            title = escape_html(&track.title),
            artist = escape_html(track.artist.as_deref().unwrap_or("Unknown Artist")),
            requested = escape_html(&track.requested_by_name)
        )
    }

    pub fn now_playing_keyboard(is_paused: bool) -> InlineKeyboardMarkup {
        let pause_btn = if is_paused {
            InlineKeyboardButton::callback("▶️ Resume", "cb_toggle_pause")
        } else {
            InlineKeyboardButton::callback("⏸️ Pause", "cb_toggle_pause")
        };
        let row1 = vec![
            pause_btn,
            InlineKeyboardButton::callback("⏭️ Skip", "cb_skip"),
            InlineKeyboardButton::callback("⏹️ Stop", "cb_stop"),
        ];
        let row2 = vec![
            InlineKeyboardButton::callback("🔄 Loop", "cb_loop"),
            InlineKeyboardButton::callback("🔀 Shuffle", "cb_shuffle"),
        ];
        InlineKeyboardMarkup::new(vec![row1, row2])
    }

    pub fn format_queue(current: Option<&Track>, queue: &[Track], _loop_mode: &LoopMode) -> String {
        let mut out = String::from(
            "☠️ <b>BROOK'S CONCERT SETLIST</b> ☠️\n\
             ──────────────────────────────\n\
             <blockquote>",
        );

        match current {
            Some(curr) => {
                out.push_str(&format!(
                    "▶️ <b>Now Playing:</b> <code>{}</code>\n   👤 {}\n\n",
                    escape_html(&curr.title),
                    escape_html(&curr.requested_by_name)
                ));
            }
            None => {
                out.push_str("⏸️ Stage is idle.\n\n");
            }
        }

        if queue.is_empty() {
            out.push_str("<i>(No upcoming tracks queued)</i>");
        } else {
            out.push_str("<b>Upcoming Tracks:</b>\n");
            for (i, t) in queue.iter().enumerate().take(10) {
                out.push_str(&format!(
                    "{}. <code>{}</code> — {}\n",
                    i + 1,
                    escape_html(&t.title),
                    escape_html(&t.requested_by_name)
                ));
            }
            if queue.len() > 10 {
                out.push_str(&format!("\n<i>...and {} more</i>", queue.len() - 10));
            }
        }

        out.push_str(
            "</blockquote>\n\
             <i>🎻 Yohohoho! The setlist never ends! 🎻</i>",
        );
        out
    }

    pub fn format_start(name: &str) -> String {
        format!(
            "💀 <b>YOHOHOHO!</b> Welcome to Brook's Songbook, <b>{name}</b>! 💀\n\
             ──────────────────────────────\n\
             <blockquote>\
             <i>\"A concert is best when every soul in the room feels it!\"</i>\n\
             — Brook, Musician of the Straw Hat Pirates\n\n\
             🎻 I'm <b>Soul King Brook</b>, the musician of the Straw Hat Pirates!\n\n\
             🎵 Play your favorite tunes, vibe to any mood, and let your soul\n\
             dance to Binks' Sake!\n\n\
             💡 Start with <code>/help</code> or jump straight in with <code>/play &lt;song name&gt;</code>.\
             </blockquote>\n\n\
             💀 <i>\"May your evenings be lively, your hearts be light, and your speakers never quiet. Yohohoho!\"</i>",
            name = escape_html(name)
        )
    }

    pub fn help_keyboard() -> InlineKeyboardMarkup {
        let row1 = vec![
            InlineKeyboardButton::callback("🎵 Music", "help_music"),
            InlineKeyboardButton::callback("🎛 Playback", "help_playback"),
            InlineKeyboardButton::callback("📋 Queue", "help_queue"),
        ];
        let row2 = vec![
            InlineKeyboardButton::callback("🎙 Voice Chat", "help_voice"),
            InlineKeyboardButton::callback("🛡️ Permissions", "help_permissions"),
            InlineKeyboardButton::callback("⚙️ Settings", "help_settings"),
        ];
        let row3 = vec![InlineKeyboardButton::callback(
            "ℹ️ Information",
            "help_info",
        )];
        InlineKeyboardMarkup::new(vec![row1, row2, row3])
    }

    pub fn format_help_main() -> String {
        "🎩 <b>𝗕𝗥𝗢𝗢𝗞 𝗕𝗢𝗧 - Features</b>\n\n\
         ★ ∘ ━━━━━━━┉┅╍\n\
         <blockquote>\
         Select a category below using the interactive buttons to explore detailed commands, features, and permissions:\n\n\
         🎵 <b>Music</b> : Search & stream audio or video\n\
         🎛 <b>Playback</b> : Control the active playback session\n\
         📋 <b>Queue</b> : Manage your concert setlist & queue\n\
         🎙 <b>Voice Chat</b> : Voice chat status & diagnostics\n\
         🛡️ <b>Permissions</b> : Access control & security\n\
         ⚙️ <b>Settings</b> : Configure your Brook experience\n\
         ℹ️ <b>Information</b> : Learn more about Soul King Brook\n\
         </blockquote>\n\
         ★ ∘ ━━━━━━━━┉┅╍\n\n\
         🎻 <i>Select a category button below! 🎻</i>".to_string()
    }

    pub fn format_help_category(category: &str) -> String {
        match category {
            "help_music" => {
                "🎵 <b>MUSIC COMMANDS</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 🌐 <code>/play &lt;title or URL&gt;</code>\n\
                 • Stream audio into Telegram Voice Chat.\n\
                 • Title requests go to AI Receiver -> Router -> Providers.\n\n\
                 🌐 <code>/vplay &lt;title or URL&gt;</code>\n\
                 • Stream video audio into Telegram Voice Chat.\n\n\
                 <i>Permissions: Anyone can request tracks to be enqueued.</i>\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
            "help_playback" => {
                "🎛 <b>PLAYBACK CONTROLS</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 🔒 <code>/pause</code> — Pause current audio stream\n\
                 🔒 <code>/resume</code> — Resume paused audio stream\n\
                 🔒 <code>/skip</code> — Skip active track & advance setlist\n\
                 🔒 <code>/prev</code> — Play previous history track\n\
                 🔒 <code>/stop</code> — Stop playback & clear setlist\n\
                 🔒 <code>/seek &lt;secs&gt;</code> — Seek to position in seconds\n\
                 🔒 <code>/volume &lt;1-200&gt;</code> — Adjust playback volume\n\n\
                 <i>Permissions: 🔒 Session Controller / Chat Admin / Bot Owner.</i>\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
            "help_queue" => {
                "📋 <b>QUEUE & SETLIST COMMANDS</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 🌐 <code>/queue</code> — Display current concert setlist\n\
                 🌐 <code>/now</code> — View now playing card with live progress bar\n\
                 🔒 <code>/loop</code> — Toggle loop mode (Off ➡️ Track 🔂 Queue 🔁)\n\
                 🔒 <code>/shuffle</code> — Randomize upcoming queue order\n\n\
                 <i>Permissions: /queue & /now are Public. Loop & Shuffle require Session Controller.</i>\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
            "help_voice" => {
                "🎙 <b>VOICE CHAT & DIAGNOSTICS</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 🌐 <code>/playerdebug</code> — View real-time player diagnostics, VoiceState, EngineState, and generation tokens.\n\n\
                 <i>The assistant account automatically joins Telegram Voice Chats when music is played.</i>\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
            "help_permissions" => {
                "🛡️ <b>PERMISSIONS & SECURITY POLICY</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 <b>Role Hierarchy:</b>\n\
                 • 👑 <b>Bot Owner</b> — Global administrative override.\n\
                 • 🛡️ <b>Chat Admin</b> — Group administrator override.\n\
                 • 🔒 <b>Session Controller</b> — User who initiated active playback.\n\
                 • 🌐 <b>Public User</b> — Can view queue, now playing, & enqueue tracks.\n\n\
                 <i>Interruption Protection: Non-controllers can enqueue tracks safely behind the active setlist without interrupting current music.</i>\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
            "help_settings" => {
                "⚙️ <b>SETTINGS & CONFIGURATION</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 • <b>Memory-First Mode:</b> Standalone runtime execution with 0 DB latency.\n\
                 • <b>Piped HTTP Stream Proxy:</b> Direct memory streaming into WebRTC.\n\
                 • <b>Max Queue Limit:</b> 100 tracks per chat.\n\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
            _ => {
                "ℹ️ <b>ABOUT SOUL KING BROOK</b>\n\
                 ──────────────────────────────\n\
                 <blockquote>\
                 🎻 <b>Brook (Soul King)</b> — Musician of the Straw Hat Pirates!\n\
                 Powered by Modular Rust Engine v0.2.0 & Teloxide.\n\n\
                 <i>🎻 Yohohoho! Feel the music in your bones! 🎻</i>\
                 </blockquote>\n\n\
                 🎻 <i>Select a category button below! 🎻</i>".to_string()
            }
        }
    }
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum PermissionLevel {
    Public,
    SessionController,
    Admin,
    Owner,
}

pub struct AuthorizationManager;

impl AuthorizationManager {
    pub fn required_permission(cmd: &BotCommand) -> PermissionLevel {
        match cmd {
            BotCommand::Start
            | BotCommand::Help
            | BotCommand::Queue
            | BotCommand::Now
            | BotCommand::PlayerDebug => PermissionLevel::Public,
            BotCommand::Play(_) | BotCommand::Vplay(_) => PermissionLevel::Public,
            BotCommand::Pause
            | BotCommand::Resume
            | BotCommand::Skip
            | BotCommand::Prev
            | BotCommand::Stop
            | BotCommand::Seek(_)
            | BotCommand::Volume(_)
            | BotCommand::Loop
            | BotCommand::Shuffle => PermissionLevel::SessionController,
            BotCommand::NewFed(_)
            | BotCommand::DelFed(_)
            | BotCommand::FedInfo(_)
            | BotCommand::JoinFed(_)
            | BotCommand::LeaveFed
            | BotCommand::FBan(_)
            | BotCommand::UnFBan(_)
            | BotCommand::SubFed(_)
            | BotCommand::UnSubFed(_)
            | BotCommand::FedSubs(_)
            | BotCommand::QuietFed(_)
            | BotCommand::FedStat(_)
            | BotCommand::FBanStat(_)
            | BotCommand::Feds
            | BotCommand::FedPromote(_)
            | BotCommand::FedDemote(_)
            | BotCommand::FBanList(_)
            | BotCommand::FedReason(_)
            | BotCommand::SetFedLog(_)
            | BotCommand::UnsetFedLog(_) => PermissionLevel::Public,
        }
    }

    pub fn authorize(
        cmd: &BotCommand,
        user_id: i64,
        chat_id: i64,
        pb_state: &crate::media_engine::PlaybackState,
        bot_owner_id: Option<i64>,
        is_admin: bool,
    ) -> Result<bool, crate::error::BotError> {
        let req_level = Self::required_permission(cmd);
        if req_level == PermissionLevel::Public {
            return Ok(true);
        }

        if bot_owner_id == Some(user_id) || is_admin {
            return Ok(true);
        }

        if let Some(controller_id) = pb_state.owner_user_id {
            if controller_id == user_id {
                return Ok(true);
            }
            let controller_name = if pb_state.owner_user_name.is_empty() {
                "Active Controller"
            } else {
                &pb_state.owner_user_name
            };
            return Err(crate::error::BotError::Unauthorized(format!(
                "Permission Denied: Only the Session Controller (<b>{}</b>) or Chat Admins can execute control commands in chat <code>{}</code>.",
                escape_html(controller_name),
                chat_id
            )));
        }

        Ok(true)
    }
}

#[allow(dead_code)]
pub struct PermissionManager {
    pub owner_id: Option<i64>,
}

#[allow(dead_code)]
impl PermissionManager {
    pub fn new(owner_id: Option<i64>) -> Self {
        Self { owner_id }
    }

    pub fn is_owner(&self, user_id: i64) -> bool {
        self.owner_id.map(|id| id == user_id).unwrap_or(false)
    }
}

#[derive(BotCommands, Clone, Debug)]
#[command(description = "Soul King Bot Commands:")]
pub enum BotCommand {
    #[command(description = "Start the bot", rename = "start")]
    Start,
    #[command(description = "Show help menu", rename = "help")]
    Help,
    #[command(description = "Play audio title or URL", rename = "play")]
    Play(String),
    #[command(description = "Play video title or URL", rename = "vplay")]
    Vplay(String),
    #[command(description = "Pause playback", rename = "pause")]
    Pause,
    #[command(description = "Resume playback", rename = "resume")]
    Resume,
    #[command(description = "Skip current track", rename = "skip")]
    Skip,
    #[command(description = "Play previous track", rename = "prev")]
    Prev,
    #[command(description = "Stop playback & clear queue", rename = "stop")]
    Stop,
    #[command(description = "Seek position in seconds", rename = "seek")]
    Seek(u64),
    #[command(description = "Set volume level (1-100)", rename = "volume")]
    Volume(u32),
    #[command(description = "Show current queue", rename = "queue")]
    Queue,
    #[command(description = "Show currently playing track", rename = "now")]
    Now,
    #[command(description = "Cycle loop mode", rename = "loop")]
    Loop,
    #[command(description = "Shuffle queue", rename = "shuffle")]
    Shuffle,
    #[command(description = "Show player debug diagnostics", rename = "playerdebug")]
    PlayerDebug,
    #[command(description = "Create a new federation", rename = "newfed")]
    NewFed(String),
    #[command(description = "Delete a federation", rename = "delfed")]
    DelFed(String),
    #[command(description = "Get federation information", rename = "fedinfo")]
    FedInfo(String),
    #[command(description = "Join a federation", rename = "joinfed")]
    JoinFed(String),
    #[command(description = "Leave current federation", rename = "leavefed")]
    LeaveFed,
    #[command(description = "Issue a federation ban", rename = "fban")]
    FBan(String),
    #[command(description = "Remove a federation ban", rename = "unfban")]
    UnFBan(String),
    #[command(description = "Subscribe to a federation", rename = "subfed")]
    SubFed(String),
    #[command(description = "Unsubscribe from a federation", rename = "unsubfed")]
    UnSubFed(String),
    #[command(description = "List federation subscriptions", rename = "fedsubs")]
    FedSubs(String),
    #[command(description = "Toggle quiet mode in group", rename = "quietfed")]
    QuietFed(String),
    #[command(description = "Show user federation status", rename = "fedstat")]
    FedStat(String),
    #[command(description = "Check fban status in fed", rename = "fbanstat")]
    FBanStat(String),
    #[command(description = "List public federations", rename = "feds")]
    Feds,
    #[command(description = "Promote federation admin", rename = "fedpromote")]
    FedPromote(String),
    #[command(description = "Demote federation admin", rename = "feddemote")]
    FedDemote(String),
    #[command(description = "Export federation ban list", rename = "fbanlist")]
    FBanList(String),
    #[command(description = "Toggle mandatory reason setting", rename = "fedreason")]
    FedReason(String),
    #[command(description = "Set federation log channel/group", rename = "setfedlog")]
    SetFedLog(String),
    #[command(description = "Unset federation log channel/group", rename = "unsetfedlog")]
    UnsetFedLog(String),
}

#[allow(clippy::too_many_arguments)]
pub async fn handle_command(
    bot: Bot,
    msg: Message,
    cmd: BotCommand,
    ai: Arc<AiReceiver>,
    media_engine: Arc<MediaEngine>,
    lazy_providers: Arc<crate::LazyProviders>,
    fed_service: Arc<crate::federation::FederationService>,
) -> anyhow::Result<()> {
    let chat_id = msg.chat.id.0;
    let pb_state = media_engine.reconcile_session(chat_id).await?;
    let user_id = msg.from.as_ref().map(|u| u.id.0 as i64).unwrap_or(0);
    let user_name = msg
        .from
        .as_ref()
        .map(|u| u.first_name.clone())
        .unwrap_or_else(|| "User".into());

    if let Err(e) = AuthorizationManager::authorize(&cmd, user_id, chat_id, &pb_state, None, false)
    {
        bot.send_message(msg.chat.id, format!("❌ <b>{e}</b>"))
            .parse_mode(ParseMode::Html)
            .await?;
        return Ok(());
    }

    match cmd {
        BotCommand::Start => {
            let text = SoulKingUI::format_start(&user_name);
            bot.send_message(msg.chat.id, text)
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Help => {
            let text = SoulKingUI::format_help_main();
            let keyboard = SoulKingUI::help_keyboard();
            bot.send_message(msg.chat.id, text)
                .parse_mode(ParseMode::Html)
                .reply_markup(keyboard)
                .await?;
        }
        BotCommand::Play(query) => {
            if query.trim().is_empty() {
                bot.send_message(
                    msg.chat.id,
                    "Please specify a song title or URL e.g. <code>/play Binks Sake</code>",
                )
                .parse_mode(ParseMode::Html)
                .await?;
                return Ok(());
            }

            let track_result = if Platform::from_url(&query).is_some() {
                let live_router = build_live_router(&lazy_providers, &lazy_providers.config);
                live_router
                    .execute_search(&query, user_id, &user_name)
                    .await
            } else {
                let processed_query = ai.process_query(&query).await?;
                let live_router = build_live_router(&lazy_providers, &lazy_providers.config);
                live_router
                    .execute_search(&processed_query, user_id, &user_name)
                    .await
            };

            match track_result {
                Ok(track) => {
                    let maybe_pos = media_engine
                        .enqueue_and_play(chat_id, track.clone())
                        .await?;
                    let pb_state = media_engine.state(chat_id).await?;

                    if let Some(pos) = maybe_pos {
                        let text = SoulKingUI::format_enqueued(&track, pos);
                        bot.send_message(msg.chat.id, text)
                            .parse_mode(ParseMode::Html)
                            .await?;
                    } else if let Some(curr) = &pb_state.current {
                        let text = SoulKingUI::format_now_playing(
                            curr,
                            0,
                            false,
                            &pb_state.loop_mode,
                            pb_state.voice_state,
                            &pb_state.queue,
                        );
                        let sent = bot
                            .send_message(msg.chat.id, text)
                            .parse_mode(ParseMode::Html)
                            .reply_markup(SoulKingUI::now_playing_keyboard(false))
                            .await?;
                        let _ = media_engine
                            .repo
                            .set_player_message_id(chat_id, Some(sent.id.0))
                            .await;
                    }
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ <b>Search failed:</b> {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::Vplay(query) => {
            if query.trim().is_empty() {
                bot.send_message(
                    msg.chat.id,
                    "Please specify a video title or URL e.g. <code>/vplay video title</code>",
                )
                .parse_mode(ParseMode::Html)
                .await?;
                return Ok(());
            }

            let live_router = build_live_router(&lazy_providers, &lazy_providers.config);
            match live_router
                .execute_search(&query, user_id, &user_name)
                .await
            {
                Ok(track) => {
                    let maybe_pos = media_engine
                        .enqueue_and_play(chat_id, track.clone())
                        .await?;
                    let pb_state = media_engine.state(chat_id).await?;

                    if let Some(pos) = maybe_pos {
                        let text = SoulKingUI::format_enqueued(&track, pos);
                        bot.send_message(msg.chat.id, text)
                            .parse_mode(ParseMode::Html)
                            .await?;
                    } else if let Some(curr) = &pb_state.current {
                        let text = SoulKingUI::format_now_playing(
                            curr,
                            0,
                            false,
                            &pb_state.loop_mode,
                            pb_state.voice_state,
                            &pb_state.queue,
                        );
                        let sent = bot
                            .send_message(msg.chat.id, text)
                            .parse_mode(ParseMode::Html)
                            .reply_markup(SoulKingUI::now_playing_keyboard(false))
                            .await?;
                        let _ = media_engine
                            .repo
                            .set_player_message_id(chat_id, Some(sent.id.0))
                            .await;
                    }
                }
                Err(e) => {
                    bot.send_message(
                        msg.chat.id,
                        format!("❌ <b>Video resolution failed:</b> {e}"),
                    )
                    .parse_mode(ParseMode::Html)
                    .await?;
                }
            }
        }
        BotCommand::Pause => {
            media_engine.pause(chat_id).await?;
            bot.send_message(msg.chat.id, "⏸️ <b>Playback Paused</b>")
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Resume => {
            media_engine.resume(chat_id).await?;
            bot.send_message(msg.chat.id, "▶️ <b>Playback Resumed</b>")
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Skip => {
            let pb_state = media_engine.state(chat_id).await?;
            match media_engine.skip(chat_id).await {
                Ok(Some(next)) => {
                    let text = SoulKingUI::format_now_playing(
                        &next,
                        0,
                        false,
                        &LoopMode::Off,
                        pb_state.voice_state,
                        &pb_state.queue,
                    );
                    let sent = bot
                        .send_message(msg.chat.id, text)
                        .parse_mode(ParseMode::Html)
                        .reply_markup(SoulKingUI::now_playing_keyboard(false))
                        .await?;
                    let _ = media_engine
                        .repo
                        .set_player_message_id(chat_id, Some(sent.id.0))
                        .await;
                }
                Ok(None) => {
                    bot.send_message(msg.chat.id, "⏹️ <b>End of Queue — Stage Cleared</b>")
                        .parse_mode(ParseMode::Html)
                        .await?;
                    let _ = media_engine.repo.set_player_message_id(chat_id, None).await;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("⚠️ <b>{e}</b>"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::Prev => {
            let pb_state = media_engine.state(chat_id).await?;
            if let Some(prev) = media_engine.prev(chat_id).await? {
                let text = SoulKingUI::format_now_playing(
                    &prev,
                    0,
                    false,
                    &LoopMode::Off,
                    pb_state.voice_state,
                    &pb_state.queue,
                );
                let sent = bot
                    .send_message(msg.chat.id, text)
                    .parse_mode(ParseMode::Html)
                    .reply_markup(SoulKingUI::now_playing_keyboard(false))
                    .await?;
                let _ = media_engine
                    .repo
                    .set_player_message_id(chat_id, Some(sent.id.0))
                    .await;
            } else {
                bot.send_message(msg.chat.id, "⚠️ <b>No previous track in history</b>")
                    .parse_mode(ParseMode::Html)
                    .await?;
            }
        }
        BotCommand::Stop => {
            media_engine.stop(chat_id).await?;
            let _ = media_engine.repo.set_player_message_id(chat_id, None).await;
            bot.send_message(msg.chat.id, "⏹️ <b>Playback Stopped & Stage Cleared</b>")
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Seek(secs) => {
            media_engine.seek(chat_id, secs).await?;
            bot.send_message(msg.chat.id, format!("⏩ <b>Seeked to {secs}s</b>"))
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Volume(vol) => {
            media_engine.set_volume(chat_id, vol).await?;
            bot.send_message(msg.chat.id, format!("🔊 <b>Volume set to {vol}%</b>"))
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Queue => {
            let state = media_engine.state(chat_id).await?;
            let text =
                SoulKingUI::format_queue(state.current.as_ref(), &state.queue, &state.loop_mode);
            bot.send_message(msg.chat.id, text)
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::Now => {
            let state = media_engine.state(chat_id).await?;
            if let Some(curr) = state.current {
                let text = SoulKingUI::format_now_playing(
                    &curr,
                    state.position_secs,
                    state.is_paused,
                    &state.loop_mode,
                    state.voice_state,
                    &state.queue,
                );
                let sent = bot
                    .send_message(msg.chat.id, text)
                    .parse_mode(ParseMode::Html)
                    .reply_markup(SoulKingUI::now_playing_keyboard(state.is_paused))
                    .await?;
                let _ = media_engine
                    .repo
                    .set_player_message_id(chat_id, Some(sent.id.0))
                    .await;
            } else {
                bot.send_message(msg.chat.id, "⏸️ <b>No track currently playing</b>")
                    .parse_mode(ParseMode::Html)
                    .await?;
            }
        }
        BotCommand::Loop => {
            let mode = media_engine.repo.cycle_loop_mode(chat_id).await?;
            bot.send_message(
                msg.chat.id,
                format!("🔁 <b>Loop Mode: {}</b>", mode.display_text()),
            )
            .parse_mode(ParseMode::Html)
            .await?;
        }
        BotCommand::Shuffle => {
            media_engine.repo.shuffle(chat_id).await?;
            bot.send_message(msg.chat.id, "🔀 <b>Queue Shuffled</b>")
                .parse_mode(ParseMode::Html)
                .await?;
        }
        BotCommand::PlayerDebug => {
            let state = media_engine.state(chat_id).await?;
            let curr_title = state
                .current
                .as_ref()
                .map(|t| t.title.as_str())
                .unwrap_or("None");
            let last_err = state.last_error.as_deref().unwrap_or("None");
            let controller = if state.owner_user_name.is_empty() {
                "None".into()
            } else {
                format!(
                    "{} ({})",
                    state.owner_user_name,
                    state.owner_user_id.unwrap_or(0)
                )
            };
            let text = format!(
                "🛠️ <b>Player Debug Diagnostics</b>\n\
                 ━━━━━━━━━━━━━━━━━━━━━\n\
                 💬 <b>Chat ID:</b> <code>{chat_id}</code>\n\
                 👑 <b>Session Controller:</b> {controller}\n\
                 🔑 <b>Session ID:</b> <code>{}</code>\n\
                 🔊 <b>Voice State:</b> {}\n\
                 ⚙️ <b>Engine State:</b> {}\n\
                 🎵 <b>Current Track:</b> {}\n\
                 📊 <b>Queue Length:</b> {}\n\
                 📜 <b>History Length:</b> {}\n\
                 🔢 <b>Playback Generation:</b> {}\n\
                 🌐 <b>VC Generation:</b> {}\n\
                 ⏸️ <b>Is Paused:</b> {}\n\
                 🔊 <b>Volume:</b> {}%\n\
                 ⚠️ <b>Last Error:</b> {}",
                state.session_id,
                state.voice_state.display_text(),
                state.engine_state.display_text(),
                curr_title,
                state.queue_len,
                state.history_len,
                state.playback_generation,
                state.vc_generation,
                state.is_paused,
                state.volume,
                last_err
            );
            bot.send_message(msg.chat.id, text)
                .parse_mode(ParseMode::Html)
                .await?;
        }


        BotCommand::NewFed(args) => {
            let name = args.trim().to_string();
            if name.is_empty() {
                bot.send_message(msg.chat.id, "Please specify a federation name: <code>/newfed <name></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.create_federation(name.clone(), user_id, None).await {
                Ok(fed) => {
                    let text = format!(
                        "🏛️ <b>Federation Created Successfully</b>\n\n\
                         <b>Name:</b> {}\n\
                         <b>FedID:</b> <code>{}</code>\n\n\
                         <i>Save this FedID! Group admins will need it to join using <code>/joinfed {}</code></i>",
                        escape_html(&fed.name),
                        fed.id,
                        fed.id
                    );
                    bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ <b>Failed to create federation:</b> {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::DelFed(args) => {
            let fed_id = args.trim();
            if fed_id.is_empty() {
                bot.send_message(msg.chat.id, "Please specify a federation ID: <code>/delfed <FedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.delete_federation(fed_id, user_id).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("🗑️ <b>Federation <code>{fed_id}</code> deleted.</b>"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FedInfo(args) => {
            let fed_id = args.trim();
            if fed_id.is_empty() {
                bot.send_message(msg.chat.id, "Please specify a federation ID: <code>/fedinfo <FedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.get_federation_info(fed_id).await {
                Ok(fed) => {
                    let chats = fed_service.repository().list_federation_chats(&fed.id).await?.len();
                    let bans = fed_service.repository().list_bans(&fed.id).await?.len();
                    let subs = fed_service.repository().list_subscriptions(&fed.id).await?.len();
                    let text = format!(
                        "ℹ️ <b>Federation Information</b>\n\n\
                         <b>Name:</b> {}\n\
                         <b>ID:</b> <code>{}</code>\n\
                         <b>Owner ID:</b> <code>{}</code>\n\
                         <b>Participating Chats:</b> {}\n\
                         <b>Active Fedbans:</b> {}\n\
                         <b>Subscribed Federations:</b> {}\n\
                         <b>Require Reason:</b> {}",
                        escape_html(&fed.name),
                        fed.id,
                        fed.owner_user_id,
                        chats,
                        bans,
                        subs,
                        if fed.settings.require_reason { "Yes" } else { "No" }
                    );
                    bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::JoinFed(args) => {
            let fed_id = args.trim();
            if fed_id.is_empty() {
                bot.send_message(msg.chat.id, "Please specify a federation ID: <code>/joinfed <FedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.join_chat(fed_id, chat_id, user_id).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("✅ Chat successfully joined federation <code>{fed_id}</code>."))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::LeaveFed => {
            match fed_service.leave_chat(chat_id, user_id).await {
                Ok(fed_id) => {
                    bot.send_message(msg.chat.id, format!("🚪 Chat successfully left federation <code>{fed_id}</code>."))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FBan(args) => {
            let parts: Vec<&str> = args.trim().splitn(3, ' ').collect();
            let mut fed_id_opt = None;
            let mut target_str_opt = None;
            let mut reason_opt = None;

            if msg.reply_to_message().is_some() {
                // Reply form: /fban <fed_id> [reason]
                if let Some(f_id) = parts.first().filter(|s| !s.is_empty()) {
                    fed_id_opt = Some(*f_id);
                    if parts.len() > 1 {
                        reason_opt = Some(parts[1..].join(" "));
                    }
                }
            } else if parts.len() >= 2 {
                // Direct form: /fban <fed_id> <user_id|@username> [reason]
                fed_id_opt = Some(parts[0]);
                target_str_opt = Some(parts[1]);
                if parts.len() > 2 {
                    reason_opt = Some(parts[2].to_string());
                }
            }

            let Some(fed_id) = fed_id_opt else {
                bot.send_message(
                    msg.chat.id,
                    "Usage:\nDirect: <code>/fban <FedID> <user_id|@username> [reason]</code>\nReply: <code>/fban <FedID> [reason]</code>",
                )
                .parse_mode(ParseMode::Html)
                .await?;
                return Ok(());
            };

            let mut target_user_id = 0i64;
            let mut target_username = None;

            if let Some(reply) = msg.reply_to_message() {
                if let Some(user) = &reply.from {
                    target_user_id = user.id.0 as i64;
                    target_username = user.username.clone();
                }
            } else if let Some(target_str) = target_str_opt {
                if target_str.starts_with('@') {
                    target_username = Some(target_str.trim_start_matches('@').to_string());
                    // Assign placeholder ID if username without numeric resolution
                    target_user_id = target_str.bytes().fold(0i64, |acc, b| acc.wrapping_add(b as i64));
                } else if let Ok(parsed_id) = target_str.parse::<i64>() {
                    target_user_id = parsed_id;
                }
            }

            if target_user_id == 0 {
                bot.send_message(msg.chat.id, "❌ Could not resolve target user ID.")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }

            let reason = reason_opt.unwrap_or_default();

            match fed_service.fban(fed_id, target_user_id, target_username, reason, user_id).await {
                Ok((ban, _total, relevant)) => {
                    let text = format!(
                        "🚫 <b>Federation Ban Issued</b>\n\n\
                         <b>Target User ID:</b> <code>{}</code>\n\
                         <b>Federation ID:</b> <code>{}</code>\n\
                         <b>Reason:</b> {}\n\
                         <b>Active Enforcement:</b> Queued in {} relevant chat(s)",
                        ban.user_id,
                        ban.federation_id,
                        escape_html(&ban.reason),
                        relevant
                    );
                    bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::UnFBan(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            let mut fed_id_opt = None;
            let mut target_str_opt = None;

            if msg.reply_to_message().is_some() {
                if let Some(f_id) = parts.first() {
                    fed_id_opt = Some(*f_id);
                }
            } else if parts.len() >= 2 {
                fed_id_opt = Some(parts[0]);
                target_str_opt = Some(parts[1]);
            }

            let Some(fed_id) = fed_id_opt else {
                bot.send_message(
                    msg.chat.id,
                    "Usage:\nDirect: <code>/unfban <FedID> <user_id></code>\nReply: <code>/unfban <FedID></code>",
                )
                .parse_mode(ParseMode::Html)
                .await?;
                return Ok(());
            };

            let mut target_user_id = 0i64;
            if let Some(reply) = msg.reply_to_message() {
                if let Some(user) = &reply.from {
                    target_user_id = user.id.0 as i64;
                }
            } else if let Some(target_str) = target_str_opt {
                if let Ok(parsed) = target_str.parse::<i64>() {
                    target_user_id = parsed;
                }
            }

            if target_user_id == 0 {
                bot.send_message(msg.chat.id, "❌ Could not resolve target user ID.")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }

            match fed_service.unfban(fed_id, target_user_id, user_id).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("✅ User <code>{target_user_id}</code> has been unfbanned from federation <code>{fed_id}</code>."))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::SubFed(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.len() < 2 {
                bot.send_message(msg.chat.id, "Usage: <code>/subfed <SourceFedID> <TargetFedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.add_subscription(parts[0], parts[1], user_id).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("🔗 Federation <code>{}</code> subscribed to <code>{}</code>.", parts[0], parts[1]))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::UnSubFed(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.len() < 2 {
                bot.send_message(msg.chat.id, "Usage: <code>/unsubfed <SourceFedID> <TargetFedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.remove_subscription(parts[0], parts[1], user_id).await {
                Ok(removed) => {
                    if removed {
                        bot.send_message(msg.chat.id, format!("✂️ Unsubscribed federation <code>{}</code> from <code>{}</code>.", parts[0], parts[1]))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    } else {
                        bot.send_message(msg.chat.id, "⚠️ Subscription not found.")
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FedSubs(args) => {
            let fed_id = args.trim();
            if fed_id.is_empty() {
                bot.send_message(msg.chat.id, "Usage: <code>/fedsubs <FedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.repository().list_subscriptions(fed_id).await {
                Ok(subs) => {
                    if subs.is_empty() {
                        bot.send_message(msg.chat.id, format!("No active subscriptions for federation <code>{fed_id}</code>."))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    } else {
                        let mut text = format!("🔗 <b>Subscriptions for Federation <code>{fed_id}</code>:</b>\n\n");
                        for s in subs {
                            text.push_str(&format!("• <code>{}</code>\n", s.target_fed_id));
                        }
                        bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                    }
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::QuietFed(args) => {
            let mode = args.trim().to_lowercase();
            let quiet = match mode.as_str() {
                "on" | "true" | "yes" | "1" => true,
                "off" | "false" | "no" | "0" => false,
                _ => {
                    bot.send_message(msg.chat.id, "Usage: <code>/quietfed on|off</code>")
                        .parse_mode(ParseMode::Html)
                        .await?;
                    return Ok(());
                }
            };
            match fed_service.set_quiet_mode(chat_id, quiet).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("🤫 <b>Quiet Mode set to: {}</b>", if quiet { "ON" } else { "OFF" }))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FedStat(args) => {
            let target_user_id = if let Ok(parsed) = args.trim().parse::<i64>() {
                parsed
            } else if let Some(reply) = msg.reply_to_message() {
                reply.from.as_ref().map(|u| u.id.0 as i64).unwrap_or(user_id)
            } else {
                user_id
            };

            match fed_service.repository().list_bans_for_user(target_user_id).await {
                Ok(bans) => {
                    if bans.is_empty() {
                        bot.send_message(msg.chat.id, format!("✅ User <code>{target_user_id}</code> has no active federation bans."))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    } else {
                        let mut text = format!("🚫 <b>Federation Bans for User <code>{target_user_id}</code>:</b>\n\n");
                        for b in bans {
                            let fed_name = fed_service.repository().get_federation(&b.federation_id).await?.map(|f| f.name).unwrap_or(b.federation_id);
                            text.push_str(&format!("• <b>{}</b>\n  Reason: {}\n\n", escape_html(&fed_name), escape_html(&b.reason)));
                        }
                        bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                    }
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FBanStat(args) => {
            let fed_id = args.trim();
            if fed_id.is_empty() {
                bot.send_message(msg.chat.id, "Usage: <code>/fbanstat <FedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.repository().get_ban(fed_id, user_id).await {
                Ok(Some(ban)) => {
                    let text = format!(
                        "🚫 <b>Federation Ban Status</b>\n\n\
                         <b>Federation:</b> <code>{}</code>\n\
                         <b>Status:</b> BANNED\n\
                         <b>Reason:</b> {}",
                        fed_id,
                        escape_html(&ban.reason)
                    );
                    bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                }
                _ => {
                    bot.send_message(msg.chat.id, format!("✅ You are NOT banned in federation <code>{fed_id}</code>."))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::Feds => {
            match fed_service.list_public_federations().await {
                Ok(feds) => {
                    if feds.is_empty() {
                        bot.send_message(msg.chat.id, "No public federations registered.")
                            .parse_mode(ParseMode::Html)
                            .await?;
                    } else {
                        let mut text = String::from("🏛️ <b>Public Federations:</b>\n\n");
                        for f in feds {
                            text.push_str(&format!("• <b>{}</b> (ID: <code>{}</code>)\n", escape_html(&f.name), f.id));
                        }
                        bot.send_message(msg.chat.id, text).parse_mode(ParseMode::Html).await?;
                    }
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FedPromote(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.len() < 2 {
                bot.send_message(msg.chat.id, "Usage: <code>/fedpromote <FedID> <user_id></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            if let Ok(target_id) = parts[1].parse::<i64>() {
                match fed_service.add_admin(parts[0], target_id, user_id).await {
                    Ok(_) => {
                        bot.send_message(msg.chat.id, format!("👤 User <code>{target_id}</code> promoted to admin in federation <code>{}</code>.", parts[0]))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                    Err(e) => {
                        bot.send_message(msg.chat.id, format!("❌ {e}"))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                }
            }
        }
        BotCommand::FedDemote(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.len() < 2 {
                bot.send_message(msg.chat.id, "Usage: <code>/feddemote <FedID> <user_id></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            if let Ok(target_id) = parts[1].parse::<i64>() {
                match fed_service.remove_admin(parts[0], target_id, user_id).await {
                    Ok(_) => {
                        bot.send_message(msg.chat.id, format!("👤 User <code>{target_id}</code> demoted in federation <code>{}</code>.", parts[0]))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                    Err(e) => {
                        bot.send_message(msg.chat.id, format!("❌ {e}"))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                }
            }
        }
        BotCommand::FBanList(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.is_empty() {
                bot.send_message(msg.chat.id, "Usage: <code>/fbanlist <FedID> [csv|json|jsonl]</code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            let fed_id = parts[0];
            let format = parts.get(1).copied().unwrap_or("csv");
            match fed_service.export_fban_list(fed_id, format).await {
                Ok(content) => {
                    let file = teloxide::types::InputFile::memory(content.into_bytes()).file_name(format!("fbanlist_{fed_id}.{format}"));
                    bot.send_document(msg.chat.id, file).await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::FedReason(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.len() < 2 {
                bot.send_message(msg.chat.id, "Usage: <code>/fedreason <FedID> on|off</code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            let required = match parts[1].to_lowercase().as_str() {
                "on" | "true" | "1" => true,
                "off" | "false" | "0" => false,
                _ => false,
            };
            match fed_service.set_reason_required(parts[0], required, user_id).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("⚙️ Mandatory reason for federation <code>{}</code> set to: <b>{}</b>", parts[0], if required { "ON" } else { "OFF" }))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
        BotCommand::SetFedLog(args) => {
            let parts: Vec<&str> = args.trim().split_whitespace().collect();
            if parts.len() < 2 {
                bot.send_message(msg.chat.id, "Usage: <code>/setfedlog <FedID> <log_chat_id></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            if let Ok(log_id) = parts[1].parse::<i64>() {
                match fed_service.set_log_chat(parts[0], Some(log_id), user_id).await {
                    Ok(_) => {
                        bot.send_message(msg.chat.id, format!("🪵 Log channel for federation <code>{}</code> set to <code>{log_id}</code>.", parts[0]))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                    Err(e) => {
                        bot.send_message(msg.chat.id, format!("❌ {e}"))
                            .parse_mode(ParseMode::Html)
                            .await?;
                    }
                }
            }
        }
        BotCommand::UnsetFedLog(args) => {
            let fed_id = args.trim();
            if fed_id.is_empty() {
                bot.send_message(msg.chat.id, "Usage: <code>/unsetfedlog <FedID></code>")
                    .parse_mode(ParseMode::Html)
                    .await?;
                return Ok(());
            }
            match fed_service.set_log_chat(fed_id, None, user_id).await {
                Ok(_) => {
                    bot.send_message(msg.chat.id, format!("🪵 Log channel for federation <code>{fed_id}</code> unset."))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
                Err(e) => {
                    bot.send_message(msg.chat.id, format!("❌ {e}"))
                        .parse_mode(ParseMode::Html)
                        .await?;
                }
            }
        }
    }
    Ok(())
}

pub async fn handle_callback_query(
    bot: Bot,
    q: teloxide::types::CallbackQuery,
    media_engine: Arc<MediaEngine>,
) -> anyhow::Result<()> {
    let Some(msg) = q.message else {
        return Ok(());
    };
    let chat_id = msg.chat().id.0;
    let msg_id = msg.id();
    let user_id = q.from.id.0 as i64;
    let data = q.data.as_deref().unwrap_or("");

    let pb_state = media_engine.reconcile_session(chat_id).await?;

    if data.starts_with("help_") {
        let text = SoulKingUI::format_help_category(data);
        let keyboard = SoulKingUI::help_keyboard();
        let _ = bot
            .edit_message_text(msg.chat().id, msg_id, text)
            .parse_mode(ParseMode::Html)
            .reply_markup(keyboard)
            .await;
        let _ = bot.answer_callback_query(&q.id).await;
        return Ok(());
    }

    let mapped_cmd = match data {
        "cb_toggle_pause" => {
            if pb_state.is_paused {
                BotCommand::Resume
            } else {
                BotCommand::Pause
            }
        }
        "cb_skip" => BotCommand::Skip,
        "cb_stop" => BotCommand::Stop,
        "cb_loop" => BotCommand::Loop,
        "cb_shuffle" => BotCommand::Shuffle,
        _ => return Ok(()),
    };

    if let Err(e) =
        AuthorizationManager::authorize(&mapped_cmd, user_id, chat_id, &pb_state, None, false)
    {
        let _ = bot
            .answer_callback_query(&q.id)
            .text(format!("⛔ {e}"))
            .show_alert(true)
            .await;
        return Ok(());
    }

    match data {
        "cb_toggle_pause" => {
            if pb_state.is_paused {
                let _ = media_engine.resume(chat_id).await;
                let _ = bot
                    .answer_callback_query(&q.id)
                    .text("▶️ Playback Resumed")
                    .await;
            } else {
                let _ = media_engine.pause(chat_id).await;
                let _ = bot
                    .answer_callback_query(&q.id)
                    .text("⏸️ Playback Paused")
                    .await;
            }
        }
        "cb_skip" => {
            let _ = media_engine.skip(chat_id).await;
            let _ = bot
                .answer_callback_query(&q.id)
                .text("⏭️ Track Skipped")
                .await;
        }
        "cb_stop" => {
            let _ = media_engine.stop(chat_id).await;
            let _ = media_engine.repo.set_player_message_id(chat_id, None).await;
            let _ = bot
                .answer_callback_query(&q.id)
                .text("⏹️ Playback Stopped")
                .await;
        }
        "cb_loop" => {
            let mode = media_engine.repo.cycle_loop_mode(chat_id).await?;
            let _ = bot
                .answer_callback_query(&q.id)
                .text(format!("🔁 Loop Mode: {}", mode.display_text()))
                .await;
        }
        "cb_shuffle" => {
            let _ = media_engine.repo.shuffle(chat_id).await;
            let _ = bot
                .answer_callback_query(&q.id)
                .text("🔀 Queue Shuffled")
                .await;
        }
        _ => {}
    }

    if let Ok(state) = media_engine.state(chat_id).await {
        if let Some(curr) = &state.current {
            let text = SoulKingUI::format_now_playing(
                curr,
                state.position_secs,
                state.is_paused,
                &state.loop_mode,
                state.voice_state,
                &state.queue,
            );
            let keyboard = SoulKingUI::now_playing_keyboard(state.is_paused);
            let _ = bot
                .edit_message_text(msg.chat().id, msg_id, text)
                .parse_mode(ParseMode::Html)
                .reply_markup(keyboard)
                .await;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bot_command_parsing() {
        let cmd = BotCommand::parse("/play reha", "mybot");
        assert!(cmd.is_ok(), "Failed to parse /play reha: {:?}", cmd);
        let cmd2 = BotCommand::parse("/start", "mybot");
        assert!(cmd2.is_ok(), "Failed to parse /start: {:?}", cmd2);
    }
}
