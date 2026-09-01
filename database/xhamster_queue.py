"""Persistent xHamster queue storage.

This module is deliberately independent from the downloader. It stores only
small job metadata in MongoDB and never stores media files in the database.
"""
import time
import uuid
import logging
from config import Config
from database.users_chats_db import db

logger = logging.getLogger(__name__)


def _collection():
    if getattr(db, "_use_fb", True):
        return None
    return db.db["xhamster_queue"]


async def create_job(owner_id, chat_id, title, source_url, items):
    job_id = uuid.uuid4().hex[:16]
    doc = {
        "job_id": job_id,
        "owner_id": int(owner_id),
        "chat_id": int(chat_id),
        "title": str(title or "xHamster Channel")[:200],
        "source_url": str(source_url or "")[:1000],
        "items": [
            {"url": str(x.get("url", ""))[:1000],
             "title": str(x.get("title", "Video"))[:200],
             "duration": str(x.get("duration", ""))[:30],
             "status": "pending", "attempts": 0}
            for x in items if x.get("url")
        ],
        "status": "queued", "created_at": time.time(), "updated_at": time.time(),
    }
    col = _collection()
    if col is not None:
        await col.insert_one(doc)
    return job_id


async def get_job(job_id):
    col = _collection()
    if col is None:
        return None
    return await col.find_one({"job_id": job_id})


async def update_job(job_id, **fields):
    col = _collection()
    if col is None:
        return False
    fields["updated_at"] = time.time()
    await col.update_one({"job_id": job_id}, {"$set": fields})
    return True


async def claim_next_item(job_id):
    col = _collection()
    if col is None:
        return None
    job = await col.find_one({"job_id": job_id, "status": {"$in": ["queued", "running"]}})
    if not job:
        return None
    for index, item in enumerate(job.get("items", [])):
        if item.get("status") == "pending":
            await col.update_one(
                {"job_id": job_id, f"items.{index}.status": "pending"},
                {"$set": {f"items.{index}.status": "running", "status": "running", "updated_at": time.time()},
                 "$inc": {f"items.{index}.attempts": 1}}
            )
            item["index"] = index
            item["status"] = "running"
            return item
    await update_job(job_id, status="completed")
    return None


async def finish_item(job_id, index, status="completed", error=""):
    col = _collection()
    if col is None:
        return False
    update = {f"items.{int(index)}.status": status, "updated_at": time.time()}
    if error:
        update[f"items.{int(index)}.error"] = str(error)[:500]
    await col.update_one({"job_id": job_id}, {"$set": update})
    return True


async def cancel_job(job_id):
    return await update_job(job_id, status="cancelled")


async def pause_job(job_id):
    return await update_job(job_id, status="paused")


async def resume_job(job_id):
    return await update_job(job_id, status="queued")
