import asyncio
import logging
from database.users_chats_db import db

logger = logging.getLogger(__name__)

# Track paused bulk jobs for users so we can resume them
# Format: user_id -> list of paused job metadata
_paused_jobs_cache = {}

async def pause_bulk_jobs(user_id: int) -> list:
    """
    Finds and pauses any running bulk/channel downloads for the given user.
    Returns a list of paused job descriptors.
    """
    paused_list = []
    user_id = int(user_id)
    
    # 1. Check and Pause Eporner active jobs
    try:
        from plugins.eporner_upgrade import _EP_JOBS
        for job_id, job in list(_EP_JOBS.items()):
            if int(job.get("owner_id", 0)) == user_id and job.get("status") in ("running", "queued"):
                job["status"] = "paused"
                logger.info(f"Preemption: Paused active Eporner bulk job {job_id} for user {user_id}")
                paused_list.append({
                    "engine": "eporner",
                    "job_id": job_id,
                    "user": job.get("user"),
                    "status_msg": job.get("status_msg") or job.get("msg")
                })
    except Exception as e:
        logger.warning(f"Error checking Eporner jobs for preemption: {e}")

    # 2. Check and Pause xHamster active jobs
    try:
        col = db.db["xhamster_queue"] if not getattr(db, "_use_fb", True) else None
        if col is not None:
            active_xh_jobs = await col.find({"owner_id": user_id, "status": {"$in": ["queued", "running"]}}).to_list(length=10)
            for job in active_xh_jobs:
                job_id = job["job_id"]
                await col.update_one({"job_id": job_id}, {"$set": {"status": "paused"}})
                logger.info(f"Preemption: Paused active xHamster bulk job {job_id} for user {user_id}")
                
                # Retrieve standard log chat/user/msg metadata if possible
                paused_list.append({
                    "engine": "xhamster",
                    "job_id": job_id,
                    "user": job.get("owner_id"), # fallback user_id
                })
    except Exception as e:
        logger.warning(f"Error checking xHamster jobs for preemption: {e}")

    if paused_list:
        _paused_jobs_cache[user_id] = paused_list
        
    return paused_list

async def resume_bulk_jobs(user_id: int, client) -> bool:
    """
    Resumes any previously paused bulk/channel downloads for the given user.
    """
    user_id = int(user_id)
    paused_list = _paused_jobs_cache.pop(user_id, [])
    
    if not paused_list:
        # Fallback: check if we can query from DB for xhamster
        try:
            col = db.db["xhamster_queue"] if not getattr(db, "_use_fb", True) else None
            if col is not None:
                paused_xh_jobs = await col.find({"owner_id": user_id, "status": "paused"}).to_list(length=10)
                for job in paused_xh_jobs:
                    paused_list.append({
                        "engine": "xhamster",
                        "job_id": job["job_id"],
                        "user": job.get("owner_id")
                    })
        except Exception:
            pass

    if not paused_list:
        return False

    logger.info(f"Preemption: Resuming {len(paused_list)} paused bulk jobs for user {user_id}")
    
    for job_info in paused_list:
        engine = job_info["engine"]
        job_id = job_info["job_id"]
        
        if engine == "eporner":
            try:
                from plugins.eporner_upgrade import _EP_JOBS, _ep_full_queue_worker
                job = _EP_JOBS.get(job_id)
                if job:
                    job["status"] = "running"
                    # Spawn worker task
                    status_msg = job_info.get("status_msg")
                    if status_msg:
                        asyncio.create_task(_ep_full_queue_worker(client, job_id, job_info.get("user"), status_msg))
                        logger.info(f"Preemption: Resumed Eporner bulk job {job_id}")
            except Exception as e:
                logger.error(f"Failed to resume Eporner bulk job: {e}")
                
        elif engine == "xhamster":
            try:
                from plugins.xhamster_upgrade import _xh_full_queue_worker
                col = db.db["xhamster_queue"] if not getattr(db, "_use_fb", True) else None
                if col is not None:
                    await col.update_one({"job_id": job_id}, {"$set": {"status": "queued"}})
                    
                    # Synthesize/Retrieve User and Message for worker
                    # We can fetch the original owner and chat context
                    job_doc = await col.find_one({"job_id": job_id})
                    if job_doc:
                        owner_id = job_doc["owner_id"]
                        chat_id = job_doc["chat_id"]
                        
                        # Send status message to notify user
                        status_msg = await client.send_message(chat_id, "🔄 **Resuming paused channel download queue...**")
                        
                        # Get user class from Pyrogram client
                        user_obj = await client.get_users(owner_id)
                        
                        asyncio.create_task(_xh_full_queue_worker(client, job_id, user_obj, status_msg))
                        logger.info(f"Preemption: Resumed xHamster bulk job {job_id}")
            except Exception as e:
                logger.error(f"Failed to resume xHamster bulk job: {e}")
                
    return True
