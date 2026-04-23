"""Telegram Mini App backend package entrypoint."""

from .app import api_app, app, sio

__all__ = ["app", "api_app", "sio"]
