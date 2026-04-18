#!/usr/bin/env python3
"""
Brook Music Bot - Standalone Entry Point
Run with: python muzs.py
"""
import asyncio
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from bot import main

if __name__ == "__main__":
    asyncio.run(main())
