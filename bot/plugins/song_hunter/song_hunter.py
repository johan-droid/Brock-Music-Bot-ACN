import asyncio
import logging
import random
from typing import Any, Dict, List

import bot.utils.database as app_db
from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core import call
from bot.core.music_backend import Track, music_backend
from bot.core.queue import queue_manager
from bot.plugins.song_hunter.audio_utils import download_and_trim_audio
from bot.plugins.song_hunter.game_state import GameState, game_manager
from bot.utils.permissions import get_permission_level, rate_limit, require_admin

logger = logging.getLogger(__name__)

_SEED_QUERIES = [
    "top hits",
    "pop",
    "rock",
    "dance",
    "electronic",
    "chill",
    "acoustic",
    "indie",
    "jazz",
    "classical",
    "hip hop",
    "romantic songs",
]


def _track_to_quiz_item(track: Track, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = payload.get("url") or payload.get("stream_url") or track.stream_url
    return {
        "id": str(track.track_id or payload.get("id") or payload.get("track_id") or url),
        "name": track.title or payload.get("title") or "Unknown Title",
        "artist_name": track.artist or payload.get("artist") or "Unknown Artist",
        "duration": int(track.duration or payload.get("duration") or 0),
        "audio": url,
        "source": payload.get("source") or track.source or "unknown",
    }


async def _build_quiz_tracks(genre: str | None, limit: int = 20) -> List[Dict[str, Any]]:
    seeds = list(_SEED_QUERIES)
    if genre:
        seeds.insert(0, genre.strip())
        seeds.insert(1, f"{genre.strip()} hits")

    random.shuffle(seeds)
    tracks: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for query in seeds:
        try:
            results = await music_backend.search(query, limit=10)
        except Exception as exc:
            logger.debug("Song Hunter search failed for %r: %s", query, exc)
            continue

        for result in results:
            try:
                payload = await music_backend.get_stream_payload(result)
            except Exception:
                continue

            if not payload or not (payload.get("url") or payload.get("stream_url")):
                continue

            quiz_item = _track_to_quiz_item(result, payload)
            dedupe_key = f"{quiz_item['id']}::{quiz_item['audio']}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            tracks.append(quiz_item)

            if len(tracks) >= limit:
                return tracks

    return tracks


async def start_round(client: Client, chat_id: int, game: GameState):
    if not game.is_active:
        return

    if game.current_round >= game.total_rounds:
        await finish_game(client, chat_id, game)
        return

    game.current_round += 1
    round_number = game.current_round
    game.answered_users.clear()
    game.first_answer_received = False

    current_track = game.tracks[round_number - 1]
    game.current_correct_track = current_track

    msg = await client.send_message(chat_id, f"🎯 **Round {round_number}/{game.total_rounds}**\n\nPreparing audio clip... 🎧")

    audio_url = current_track.get("audio")
    track_id = str(current_track.get("id") or f"{chat_id}_{round_number}")

    if not audio_url:
        await msg.edit_text("❌ Failed to get audio for this track. Skipping round...")
        await asyncio.sleep(2)
        asyncio.create_task(start_round(client, chat_id, game))
        return

    trimmed_path = await download_and_trim_audio(audio_url, track_id)
    if not trimmed_path:
        await msg.edit_text("❌ Failed to process audio. Skipping round...")
        await asyncio.sleep(2)
        asyncio.create_task(start_round(client, chat_id, game))
        return

    if not game.is_active:
        return

    try:
        if not call.call_manager:
            raise RuntimeError("Call manager is not initialized")
        await call.call_manager.play(chat_id, trimmed_path, video=False, source="song_hunter")
    except Exception as exc:
        logger.error("Failed to play quiz clip in chat %s: %s", chat_id, exc)
        await msg.edit_text("❌ Could not play quiz clip in voice chat.")
        game_manager.end_game(chat_id)
        return

    options = [current_track]
    distractors = [t for t in game.tracks if str(t.get("id")) != str(current_track.get("id"))]
    random.shuffle(distractors)
    options.extend(distractors[:3])
    random.shuffle(options)
    game.current_options = options

    keyboard = []
    for opt in options:
        label = f"{opt.get('artist_name', 'Unknown')} - {opt.get('name', 'Unknown')}"
        keyboard.append([InlineKeyboardButton(label[:60], callback_data=f"sh_ans_{round_number}_{opt['id']}")])

    await msg.edit_text(
        f"🎯 **Round {round_number}/{game.total_rounds}**\n\n"
        "🔊 **What song is this?**\n"
        "You have 15 seconds to answer!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    game.round_message_id = msg.id

    async def round_timeout():
        await asyncio.sleep(15)
        if game.is_active and game.current_round == round_number:
            await end_round(client, chat_id, game)

    game.round_timer_task = asyncio.create_task(round_timeout())


async def end_round(client: Client, chat_id: int, game: GameState):
    if not game.is_active:
        return

    correct_track = game.current_correct_track or {}
    text = f"🎯 **Round {game.current_round}/{game.total_rounds} - Finished**\n\n"
    text += f"✅ The correct answer was: **{correct_track.get('artist_name')} - {correct_track.get('name')}**\n\n"

    if game.scores:
        text += "**Current Scores:**\n"
        for uid, score in sorted(game.scores.items(), key=lambda x: x[1], reverse=True):
            text += f"• <a href='tg://user?id={uid}'>Player {uid}</a>: {score} pts\n"
    else:
        text += "No one scored this round! 😴\n"

    try:
        await client.edit_message_text(
            chat_id,
            game.round_message_id,
            text,
            reply_markup=None,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.error("Failed to edit round message: %s", exc)

    await asyncio.sleep(3)
    asyncio.create_task(start_round(client, chat_id, game))


async def finish_game(client: Client, chat_id: int, game: GameState):
    try:
        if call.call_manager:
            if game.was_playing and game.previous_queue:
                first_item = game.previous_queue[0] if game.previous_queue else None
                if first_item:
                    restored_url = first_item.get("url") or first_item.get("stream_url")
                    if restored_url:
                        await call.call_manager.play(chat_id, restored_url, video=False, source=first_item.get("source", "unknown"))
                    else:
                        await call.call_manager.leave_call(chat_id)
                else:
                    await call.call_manager.leave_call(chat_id)
            else:
                await call.call_manager.leave_call(chat_id)
    except Exception as exc:
        logger.error("Error finishing Song Hunter call state: %s", exc)

    text = "🏆 **Song Hunter - Game Over!** 🏆\n\n"
    if game.scores:
        text += "**Final Scores:**\n"
        sorted_scores = sorted(game.scores.items(), key=lambda x: x[1], reverse=True)
        for i, (uid, score) in enumerate(sorted_scores):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "•"
            text += f"{medal} <a href='tg://user?id={uid}'>Player {uid}</a>: {score} pts\n"
            try:
                if hasattr(app_db.db, "save_quiz_score"):
                    await app_db.db.save_quiz_score(uid, score)
            except Exception as exc:
                logger.error("Failed to save score for %s: %s", uid, exc)
    else:
        text += "No one scored any points! 😭\n"

    text += "\nType `/starthunter` to play again!"
    await client.send_message(chat_id, text)
    game_manager.end_game(chat_id)


@Client.on_message(filters.command(["starthunter", "sh"]) & filters.group)
@require_admin
@rate_limit
async def start_hunter(client: Client, message: Message):
    chat_id = message.chat.id
    if game_manager.get_game(chat_id):
        await message.reply_text("❌ A game is already running in this chat! Use /stophunter to end it.")
        return

    args = message.text.split(maxsplit=1)
    genre = args[1] if len(args) > 1 else None
    msg = await message.reply_text("🔍 **Song Hunter**\n\nFinding tracks from connected microservices... 🎵")

    tracks = await _build_quiz_tracks(genre=genre, limit=20)
    if len(tracks) < 5:
        await msg.edit_text("❌ Could not start quiz right now (not enough playable tracks found).")
        return

    game = game_manager.start_game(chat_id)
    game.tracks = tracks
    game.total_rounds = 5

    try:
        queue = await queue_manager.get_queue(chat_id)
        if queue:
            game.was_playing = True
            game.previous_queue = queue
        else:
            game.was_playing = False
    except Exception as exc:
        logger.error("Error getting queue state: %s", exc)
        game.was_playing = False

    await msg.edit_text(
        "🎮 **Song Hunter Started!**\n\n"
        "Get ready for 5 rounds. I will play a short clip, and you must guess the song!"
    )
    await asyncio.sleep(2)
    asyncio.create_task(start_round(client, chat_id, game))


@Client.on_message(filters.command(["stophunter", "stopsh"]) & filters.group)
@require_admin
@rate_limit
async def stop_hunter(client: Client, message: Message):
    chat_id = message.chat.id
    game = game_manager.get_game(chat_id)
    if not game:
        await message.reply_text("❌ No game is currently running!")
        return

    was_playing = game.was_playing
    previous_queue = game.previous_queue
    game_manager.end_game(chat_id)

    try:
        if call.call_manager:
            if was_playing and previous_queue:
                restored = previous_queue[0]
                restored_url = restored.get("url") or restored.get("stream_url")
                if restored_url:
                    await call.call_manager.play(chat_id, restored_url, video=False, source=restored.get("source", "unknown"))
                else:
                    await call.call_manager.leave_call(chat_id)
            else:
                await call.call_manager.leave_call(chat_id)
    except Exception:
        pass

    await message.reply_text("🛑 **Song Hunter stopped.**")


@Client.on_callback_query(filters.regex(r"^sh_ans_"))
async def handle_answer(client: Client, callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    data = callback_query.data

    if await get_permission_level(user_id, chat_id) < 1:
        await callback_query.answer("You are not allowed to play Song Hunter.", show_alert=True)
        return

    _, _, round_str, track_id = data.split("_", 3)
    round_num = int(round_str)
    game = game_manager.get_game(chat_id)

    if not game or not game.is_active or game.current_round != round_num:
        await callback_query.answer("This round is over!", show_alert=True)
        return

    if user_id in game.answered_users:
        await callback_query.answer("You already answered this round!", show_alert=True)
        return

    game.answered_users.add(user_id)
    if track_id == str(game.current_correct_track.get("id")):
        points = 10 if not game.first_answer_received else 5
        game.first_answer_received = True
        game.add_score(user_id, points)
        await callback_query.answer(f"✅ Correct! +{points} points!", show_alert=True)
    else:
        await callback_query.answer("❌ Wrong answer!", show_alert=True)


@Client.on_message(filters.command(["hunterboard", "shboard"]))
@rate_limit
async def hunter_board(client: Client, message: Message):
    msg = await message.reply_text("📊 Fetching leaderboard...")
    chat_id = message.chat.id

    try:
        if not hasattr(app_db.db, "get_top_quiz_scores"):
            await msg.edit_text("❌ Leaderboard is not available right now.")
            return

        scores = await app_db.db.get_top_quiz_scores(limit=10)
        text = "🏆 **Song Hunter Global Leaderboard** 🏆\n\n"

        if scores:
            for i, score_data in enumerate(scores):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
                uid = score_data["user_id"]
                score = score_data["score"]
                games = score_data.get("games_played", 0)
                try:
                    user = await client.get_users(uid)
                    name = user.first_name
                except Exception:
                    name = f"User {uid}"
                text += f"{medal} **{name}** - {score} pts ({games} games)\n"
        else:
            text += "No scores recorded globally yet!\n"

        chat_members = []
        try:
            async for member in client.get_chat_members(chat_id):
                chat_members.append(member.user.id)
            if chat_members:
                chat_scores = await app_db.db.get_top_quiz_scores(limit=10, user_ids=chat_members)
                if chat_scores:
                    text += "\n👥 **Chat Leaderboard** 👥\n\n"
                    for i, score_data in enumerate(chat_scores):
                        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
                        uid = score_data["user_id"]
                        score = score_data["score"]
                        games = score_data.get("games_played", 0)
                        try:
                            user = await client.get_users(uid)
                            name = user.first_name
                        except Exception:
                            name = f"User {uid}"
                        text += f"{medal} **{name}** - {score} pts ({games} games)\n"
        except Exception as exc:
            logger.error("Could not fetch chat members for leaderboard: %s", exc)

        await msg.edit_text(text)
    except Exception as exc:
        logger.error("Failed to fetch hunter board: %s", exc)
        await msg.edit_text("❌ Failed to fetch leaderboard.")
