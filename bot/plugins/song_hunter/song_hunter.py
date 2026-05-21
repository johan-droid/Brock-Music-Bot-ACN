import asyncio
import random
import logging
import json
from typing import List, Dict, Any

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pytgcalls.types import MediaStream

from bot.core.bot import bot_client
from bot.core.call import CallManager
from bot.core.queue import queue_manager
from bot.platforms.jamendo import jamendo_client
import bot.utils.database as app_db
from bot.utils.permissions import require_admin, rate_limit, get_permission_level
from bot.plugins.song_hunter.audio_utils import download_and_trim_audio
from bot.plugins.song_hunter.game_state import game_manager, GameState

logger = logging.getLogger(__name__)

async def start_round(client: Client, chat_id: int, game: GameState):
    if not game.is_active:
        return

    if game.current_round >= game.total_rounds:
        await finish_game(client, chat_id, game)
        return

    game.current_round += 1
    game.answered_users.clear()
    game.first_answer_received = False

    current_track = game.tracks[game.current_round - 1]
    game.current_correct_track = current_track

    msg = await client.send_message(chat_id, f"🎯 **Round {game.current_round}/{game.total_rounds}**\n\nPreparing audio clip... 🎧")

    audio_url = current_track.get('audio')
    track_id = current_track.get('id')

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
        call = await CallManager.get_call()
        stream = MediaStream(trimmed_path)

        try:
            await call.play(chat_id, stream)
        except Exception as e:
            logger.error(f"Error playing in chat {chat_id}: {e}")
            try:
                from bot.core.userbot import get_available_userbot
                userbot = await get_available_userbot(chat_id)
                await call.play(chat_id, stream)
            except Exception as e2:
                logger.error(f"Failed to connect and play: {e2}")
                await msg.edit_text("❌ Could not connect to Voice Chat. Is it active?")
                game_manager.end_game(chat_id)
                return

    except Exception as e:
        logger.error(f"Failed to play audio: {e}")
        await msg.edit_text("❌ Error playing audio. Skipping round...")
        await asyncio.sleep(2)
        asyncio.create_task(start_round(client, chat_id, game))
        return

    options = [current_track]

    distractors = [t for t in game.tracks if t['id'] != track_id]
    random.shuffle(distractors)

    for distractor in distractors[:3]:
        options.append(distractor)

    random.shuffle(options)
    game.current_options = options

    keyboard = []
    for i, opt in enumerate(options):
        btn = InlineKeyboardButton(f"{opt.get('artist_name', 'Unknown')} - {opt.get('name', 'Unknown')}", callback_data=f"sh_ans_{game.current_round}_{opt['id']}")
        keyboard.append([btn])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(
        f"🎯 **Round {game.current_round}/{game.total_rounds}**\n\n"
        f"🔊 **What song is this?**\n"
        f"You have 15 seconds to answer!",
        reply_markup=reply_markup
    )
    game.round_message_id = msg.id

    async def round_timeout():
        await asyncio.sleep(15)
        if game.is_active and game.current_round == int(msg.text.split('/')[0].split(' ')[-1].replace('**','')):
            await end_round(client, chat_id, game)

    game.round_timer_task = asyncio.create_task(round_timeout())

async def end_round(client: Client, chat_id: int, game: GameState):
    if not game.is_active:
        return

    correct_track = game.current_correct_track

    text = f"🎯 **Round {game.current_round}/{game.total_rounds} - Finished**\n\n"
    text += f"✅ The correct answer was: **{correct_track.get('artist_name')} - {correct_track.get('name')}**\n\n"

    if len(game.scores) > 0:
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
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed to edit round message: {e}")

    await asyncio.sleep(3)
    asyncio.create_task(start_round(client, chat_id, game))

async def finish_game(client: Client, chat_id: int, game: GameState):
    try:
        call = await CallManager.get_call()
        if game.was_playing and game.previous_queue:
            # Resume existing queue by playing the first item in the queue
            if len(game.previous_queue) > 0:
                first_item = game.previous_queue[0]
                try:
                    stream = MediaStream(first_item.get('stream_url', ''))
                    await call.play(chat_id, stream)
                except Exception as e:
                    logger.error(f"Error resuming queue: {e}")
                    await call.leave_call(chat_id)
            else:
                await call.leave_call(chat_id)
        else:
            await call.leave_call(chat_id)
    except Exception as e:
        logger.error(f"Error leaving call: {e}")

    text = "🏆 **Song Hunter - Game Over!** 🏆\n\n"

    if len(game.scores) > 0:
        text += "**Final Scores:**\n"
        sorted_scores = sorted(game.scores.items(), key=lambda x: x[1], reverse=True)

        for i, (uid, score) in enumerate(sorted_scores):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "•"
            text += f"{medal} <a href='tg://user?id={uid}'>Player {uid}</a>: {score} pts\n"

            try:
                if hasattr(app_db.db, 'save_quiz_score'):
                    await app_db.db.save_quiz_score(uid, score)
            except Exception as e:
                logger.error(f"Failed to save score for {uid}: {e}")
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

    msg = await message.reply_text("🔍 **Song Hunter**\n\nFetching random tracks from Jamendo... 🎵")

    tracks = await jamendo_client.get_random_tracks(limit=20, genre=genre)

    if not tracks or len(tracks) < 5:
        await msg.edit_text("❌ Could not start quiz, try again later. (Not enough tracks found)")
        return

    game = game_manager.start_game(chat_id)
    game.tracks = tracks
    game.total_rounds = 5

    # Save previous queue state
    try:
        from bot.core.queue import queue_manager
        queue = await queue_manager.get_queue(chat_id)
        if queue and len(queue) > 0:
            game.was_playing = True
            game.previous_queue = queue
        else:
            game.was_playing = False
    except Exception as e:
        logger.error(f"Error getting queue state: {e}")
        game.was_playing = False

    await msg.edit_text("🎮 **Song Hunter Started!**\n\nGet ready for 5 rounds. I will play a 5-8 second clip, and you must guess the song!")
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
        call = await CallManager.get_call()
        if was_playing and previous_queue and len(previous_queue) > 0:
            try:
                stream = MediaStream(previous_queue[0].get('stream_url', ''))
                await call.play(chat_id, stream)
            except Exception as e:
                logger.error(f"Error resuming queue on stop: {e}")
                await call.leave_call(chat_id)
        else:
            await call.leave_call(chat_id)
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

    _, _, round_str, track_id = data.split('_', 3)
    round_num = int(round_str)

    game = game_manager.get_game(chat_id)

    if not game or not game.is_active or game.current_round != round_num:
        await callback_query.answer("This round is over!", show_alert=True)
        return

    if user_id in game.answered_users:
        await callback_query.answer("You already answered this round!", show_alert=True)
        return

    game.answered_users.add(user_id)

    if track_id == str(game.current_correct_track['id']):
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
        if not hasattr(app_db.db, 'get_top_quiz_scores'):
            await msg.edit_text("❌ Leaderboard is not available right now.")
            return

        scores = await app_db.db.get_top_quiz_scores(limit=10)

        text = "🏆 **Song Hunter Global Leaderboard** 🏆\n\n"

        if scores:
            for i, score_data in enumerate(scores):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
                uid = score_data['user_id']
                score = score_data['score']
                games = score_data.get('games_played', 0)

                try:
                    user = await client.get_users(uid)
                    name = user.first_name
                except Exception:
                    name = f"User {uid}"

                text += f"{medal} **{name}** - {score} pts ({games} games)\n"
        else:
             text += "No scores recorded globally yet!\n"

        # Optional: Get chat-specific members
        chat_members = []
        try:
            async for member in client.get_chat_members(chat_id):
                chat_members.append(member.user.id)

            if chat_members:
                chat_scores = await app_db.db.get_top_quiz_scores(limit=10, user_ids=chat_members)
                if chat_scores:
                    text += "\n👥 **Chat Leaderboard** 👥\n\n"
                    for i, score_data in enumerate(chat_scores):
                        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
                        uid = score_data['user_id']
                        score = score_data['score']
                        games = score_data.get('games_played', 0)

                        try:
                            user = await client.get_users(uid)
                            name = user.first_name
                        except Exception:
                            name = f"User {uid}"

                        text += f"{medal} **{name}** - {score} pts ({games} games)\n"
        except Exception as e:
            logger.error(f"Could not fetch chat members for leaderboard: {e}")

        await msg.edit_text(text)
    except Exception as e:
        logger.error(f"Failed to fetch hunter board: {e}")
        await msg.edit_text("❌ Failed to fetch leaderboard.")
