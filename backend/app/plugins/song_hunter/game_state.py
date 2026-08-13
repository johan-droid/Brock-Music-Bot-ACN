import asyncio
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class GameState:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.is_active = True
        self.tracks: List[Dict[str, Any]] = []
        self.current_round = 0
        self.total_rounds = 0
        self.scores: Dict[int, int] = {}
        self.current_correct_track: Optional[Dict[str, Any]] = None
        self.current_options: List[Dict[str, Any]] = []
        self.answered_users: set = set()
        self.round_message_id: Optional[int] = None
        self.round_timer_task: Optional[asyncio.Task] = None
        self.first_answer_received = False
        self.was_playing = False
        self.previous_queue = None

    def add_score(self, user_id: int, points: int):
        if user_id not in self.scores:
            self.scores[user_id] = 0
        self.scores[user_id] += points

class GameManager:
    def __init__(self):
        self.active_games: Dict[int, GameState] = {}

    def start_game(self, chat_id: int) -> GameState:
        if chat_id in self.active_games:
            self.end_game(chat_id)
        game = GameState(chat_id)
        self.active_games[chat_id] = game
        return game

    def get_game(self, chat_id: int) -> Optional[GameState]:
        return self.active_games.get(chat_id)

    def end_game(self, chat_id: int):
        if chat_id in self.active_games:
            game = self.active_games[chat_id]
            game.is_active = False
            if game.round_timer_task and not game.round_timer_task.done():
                game.round_timer_task.cancel()
            del self.active_games[chat_id]

game_manager = GameManager()
