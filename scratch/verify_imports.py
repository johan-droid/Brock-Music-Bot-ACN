import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

print("--- Verifying Imports ---")

try:
    from pyrogram import Client, idle
    print("OK: Pyrogram (Client, idle)")
except ImportError as e:
    print(f"FAILED: Pyrogram (Client, idle) ({e})")

try:
    from Crypto.Cipher import DES
    print("OK: Pycryptodome (Crypto.Cipher.DES)")
except ImportError as e:
    print(f"FAILED: Pycryptodome (Crypto.Cipher.DES) ({e})")

try:
    from pytgcalls import PyTgCalls
    print("OK: PyTgCalls")
except ImportError as e:
    print(f"FAILED: PyTgCalls ({e})")

try:
    from pydantic import Field, field_validator
    from pydantic_settings import BaseSettings
    print("OK: Pydantic v2")
except ImportError as e:
    print(f"FAILED: Pydantic v2 ({e})")

print("--- Verification Complete ---")
