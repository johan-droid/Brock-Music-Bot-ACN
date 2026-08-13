#!/usr/bin/env python3
"""
Brook Music Bot - Minimal entrypoint
Run with: python -m app
"""
from app.__main__ import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
