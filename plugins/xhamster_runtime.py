"""Shared runtime limits for every xHamster download path."""

import asyncio

from config import Config

# One singleton shared by direct links, profile buttons and bulk queues.
XHAMSTER_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(
    Config.XHAMSTER_MAX_CONCURRENT_DOWNLOADS
)

# Splitting large files is disk-heavy; keep one split writer at a time.
XHAMSTER_SPLIT_SEMAPHORE = asyncio.Semaphore(1)
