"""Unified fair stage runtime for BIMBO media jobs.

This is intentionally a small in-memory runtime coordinator, not a downloader.
Persistent bulk item lists remain in their existing Mongo/in-memory job stores;
all actual media work passes through these shared download/upload stage slots.
"""

import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from config import Config


PRIORITY_BULK = 0
PRIORITY_NORMAL = 50
PRIORITY_INTERACTIVE = 100
_interactive_jobs = set()


@dataclass
class _Ticket:
    task_id: str
    user_id: int
    site: str
    priority: int
    created_at: float
    future: asyncio.Future


class FairStageLimiter:
    """Round-robin by user, FIFO inside each user's queue."""

    def __init__(self, name: str, limit: int, site_limits=None):
        self.name = name
        self.limit = max(1, int(limit))
        self.site_limits = {
            str(site): max(1, int(value))
            for site, value in (site_limits or {}).items()
        }
        self._active: Dict[str, _Ticket] = {}
        self._pending: Dict[int, Deque[_Ticket]] = defaultdict(deque)
        self._user_order: Deque[int] = deque()
        self._lock = asyncio.Lock()

    def _pending_count(self, user_id: Optional[int] = None) -> int:
        if user_id is None:
            return sum(len(queue) for queue in self._pending.values())
        return len(self._pending.get(int(user_id), ()))

    def snapshot(self, user_id: Optional[int] = None) -> dict:
        if user_id is None:
            active = len(self._active)
        else:
            uid = int(user_id)
            active = sum(1 for ticket in self._active.values() if ticket.user_id == uid)
        return {
            "active": active,
            "waiting": self._pending_count(user_id),
            "limit": self.limit,
        }

    def _dispatch_locked(self):
        while len(self._active) < self.limit and self._user_order:
            eligible = []
            for order_index, uid in enumerate(self._user_order):
                queue = self._pending.get(uid)
                if not queue:
                    continue
                ticket = queue[0]
                site_limit = self.site_limits.get(ticket.site)
                site_active = sum(
                    1 for active in self._active.values()
                    if active.site == ticket.site
                )
                if site_limit is not None and site_active >= site_limit:
                    continue
                # While an interactive job is waiting/running, do not start a
                # new bulk download. Already-active downloads are never killed.
                if (
                    self.name == "download" and _interactive_jobs
                    and ticket.priority < PRIORITY_INTERACTIVE
                ):
                    continue
                eligible.append((ticket.priority, -order_index, uid, ticket))

            if not eligible:
                break
            _priority, _order, uid, ticket = max(eligible, key=lambda row: (row[0], row[1]))
            try:
                self._user_order.remove(uid)
            except ValueError:
                continue
            queue = self._pending.get(uid)
            if not queue:
                continue
            queue.popleft()
            if queue:
                self._user_order.append(uid)
            else:
                self._pending.pop(uid, None)
            if ticket.future.cancelled():
                continue
            self._active[ticket.task_id] = ticket
            ticket.future.set_result(True)

    async def acquire(self, task_id: str, user_id: int, site: str = "media", priority=PRIORITY_NORMAL):
        uid = int(user_id)
        loop = asyncio.get_running_loop()
        ticket = _Ticket(
            task_id=str(task_id), user_id=uid, site=str(site),
            priority=int(priority), created_at=time.time(),
            future=loop.create_future(),
        )
        async with self._lock:
            # A task can only own one slot in a given stage.
            if task_id in self._active:
                return ticket
            queue = self._pending[uid]
            was_empty = not queue
            # Stable priority insertion: interactive single/commands jump ahead
            # of bulk items, FIFO is preserved among equal-priority tickets.
            insert_at = len(queue)
            for index, existing in enumerate(queue):
                if ticket.priority > existing.priority:
                    insert_at = index
                    break
            queue.insert(insert_at, ticket)
            if was_empty:
                self._user_order.append(uid)
            self._dispatch_locked()

        try:
            await ticket.future
            return ticket
        except BaseException:
            async with self._lock:
                queue = self._pending.get(uid)
                if queue:
                    try:
                        queue.remove(ticket)
                    except ValueError:
                        pass
                    if not queue:
                        self._pending.pop(uid, None)
                        try:
                            self._user_order.remove(uid)
                        except ValueError:
                            pass
                self._active.pop(task_id, None)
                self._dispatch_locked()
            raise

    async def release(self, task_id: str):
        async with self._lock:
            self._active.pop(str(task_id), None)
            self._dispatch_locked()

    def reset(self):
        for queue in self._pending.values():
            for ticket in queue:
                if not ticket.future.done():
                    ticket.future.cancel()
        self._active.clear()
        self._pending.clear()
        self._user_order.clear()


DOWNLOAD_STAGE = FairStageLimiter(
    "download",
    getattr(Config, "BIMBO_MAX_CONCURRENT_DOWNLOADS", 2),
    site_limits={
        "xhamster": getattr(Config, "XHAMSTER_MAX_CONCURRENT_DOWNLOADS", 1),
    },
)
UPLOAD_STAGE = FairStageLimiter(
    "upload", getattr(Config, "BIMBO_MAX_CONCURRENT_UPLOADS", 2)
)

# Bulk queues only submit one current item at a time, so their not-yet-submitted
# remainder is tracked separately for an honest dashboard pending count.
_backlogs: Dict[str, dict] = {}


async def begin_interactive_job(task_id: str):
    _interactive_jobs.add(str(task_id))


async def end_interactive_job(task_id: str):
    _interactive_jobs.discard(str(task_id))
    # Removing the barrier may make bulk tickets dispatchable again.
    async with DOWNLOAD_STAGE._lock:
        DOWNLOAD_STAGE._dispatch_locked()


def interactive_job_count() -> int:
    return len(_interactive_jobs)


def set_bulk_backlog(job_id: str, user_id: int, count: int, site="media", label=""):
    count = max(0, int(count or 0))
    if count <= 0:
        _backlogs.pop(str(job_id), None)
        return
    _backlogs[str(job_id)] = {
        "user_id": int(user_id), "count": count,
        "site": str(site), "label": str(label or "")[:80],
    }


def clear_bulk_backlog(job_id: str):
    _backlogs.pop(str(job_id), None)


def _backlog_count(user_id: Optional[int] = None) -> int:
    if user_id is None:
        return sum(item["count"] for item in _backlogs.values())
    uid = int(user_id)
    return sum(item["count"] for item in _backlogs.values() if item["user_id"] == uid)


def get_pipeline_stats(user_id: Optional[int] = None) -> dict:
    download = DOWNLOAD_STAGE.snapshot(user_id)
    upload = UPLOAD_STAGE.snapshot(user_id)
    backlog = _backlog_count(user_id)
    return {
        "download_active": download["active"],
        "download_waiting": download["waiting"],
        "download_limit": download["limit"],
        "upload_active": upload["active"],
        "upload_waiting": upload["waiting"],
        "upload_limit": upload["limit"],
        "bulk_pending": backlog,
        "interactive": len(_interactive_jobs),
        "total_pending": download["waiting"] + upload["waiting"] + backlog,
    }


async def _refresh_dashboard(client, user_id: int, force=True):
    try:
        from helper_funcs.display_progress import update_user_progress
        await update_user_progress(client, int(user_id), force=force)
    except Exception:
        pass


@asynccontextmanager
async def stage_slot(stage: str, task_id: str, user_id: int, site="media", client=None,
                     priority=PRIORITY_NORMAL, notify=True):
    limiter = DOWNLOAD_STAGE if stage == "download" else UPLOAD_STAGE
    try:
        from helper_funcs.display_progress import get_task, update_task
        current = get_task(task_id) or {}
        update_task(
            task_id,
            current.get("downloaded", 0),
            current.get("total_size", 0),
            0,
            status="waiting",
            engine=current.get("engine") or site,
        )
    except Exception:
        pass
    if notify:
        await _refresh_dashboard(client, user_id)

    await limiter.acquire(task_id, user_id, site, priority=priority)
    try:
        try:
            from helper_funcs.display_progress import get_task, update_task
            current = get_task(task_id) or {}
            update_task(
                task_id,
                current.get("downloaded", 0),
                current.get("total_size", 0),
                0,
                status="starting",
                engine=current.get("engine") or site,
            )
        except Exception:
            pass
        if notify:
            await _refresh_dashboard(client, user_id)
        yield
    finally:
        await limiter.release(task_id)
        if notify:
            await _refresh_dashboard(client, user_id)


def reset_pipeline_runtime():
    DOWNLOAD_STAGE.reset()
    UPLOAD_STAGE.reset()
    _backlogs.clear()
    _interactive_jobs.clear()
