import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from pyrogram import Client
from pyrogram.types import Message
import logging

logger = logging.getLogger(__name__)

class DownloadTask:
    def __init__(self, task_id: str, user_id: int, url: str, 
                 message: Message, priority: int = 0):
        self.task_id = task_id
        self.user_id = user_id
        self.url = url
        self.message = message
        self.priority = priority
        self.status = 'queued'  # queued, downloading, completed, failed, cancelled
        self.progress = 0
        self.speed = 0
        self.total_size = 0
        self.downloaded = 0
        self.filename = None
        self.error = None
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        
    def to_dict(self):
        return {
            'task_id': self.task_id,
            'user_id': self.user_id,
            'url': self.url,
            'priority': self.priority,
            'status': self.status,
            'progress': self.progress,
            'speed': self.speed,
            'total_size': self.total_size,
            'downloaded': self.downloaded,
            'filename': self.filename,
            'error': self.error,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }

class DownloadQueue:
    def __init__(self, max_concurrent: int = 2):
        self.queue: List[DownloadTask] = []
        self.active: Dict[str, DownloadTask] = {}
        self.completed: Dict[str, DownloadTask] = {}
        self.max_concurrent = max_concurrent
        self.lock = asyncio.Lock()
        self.processing = False
        
    async def add_task(self, task: DownloadTask) -> int:
        """Add task to queue, returns position"""
        async with self.lock:
            # Insert based on priority (higher priority first)
            insert_pos = 0
            for i, existing_task in enumerate(self.queue):
                if task.priority > existing_task.priority:
                    insert_pos = i
                    break
                insert_pos = i + 1
            
            self.queue.insert(insert_pos, task)
            logger.info(f"Task {task.task_id} added to queue at position {insert_pos + 1}")
            
            # Start processing if not already running
            if not self.processing:
                asyncio.create_task(self._process_queue())
            
            return insert_pos + 1
    
    async def remove_task(self, task_id: str) -> bool:
        """Remove task from queue"""
        async with self.lock:
            # Check in queue
            for i, task in enumerate(self.queue):
                if task.task_id == task_id:
                    self.queue.pop(i)
                    logger.info(f"Task {task_id} removed from queue")
                    return True
            
            # Check in active
            if task_id in self.active:
                task = self.active[task_id]
                task.status = 'cancelled'
                logger.info(f"Task {task_id} cancelled")
                return True
            
            return False
    
    async def get_queue_position(self, task_id: str) -> Optional[int]:
        """Get position of task in queue"""
        async with self.lock:
            for i, task in enumerate(self.queue):
                if task.task_id == task_id:
                    return i + 1
            return None
    
    async def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """Get task by ID"""
        async with self.lock:
            # Check queue
            for task in self.queue:
                if task.task_id == task_id:
                    return task
            
            # Check active
            if task_id in self.active:
                return self.active[task_id]
            
            # Check completed
            if task_id in self.completed:
                return self.completed[task_id]
            
            return None
    
    async def get_user_tasks(self, user_id: int) -> Dict[str, List[DownloadTask]]:
        """Get all tasks for a user"""
        async with self.lock:
            queued = [t for t in self.queue if t.user_id == user_id]
            active = [t for t in self.active.values() if t.user_id == user_id]
            completed = [t for t in self.completed.values() if t.user_id == user_id]
            
            return {
                'queued': queued,
                'active': active,
                'completed': completed
            }
    
    async def _process_queue(self):
        """Process queue - start downloads when slots available"""
        self.processing = True
        
        while True:
            async with self.lock:
                # Check if we can start more downloads
                if len(self.active) >= self.max_concurrent:
                    await asyncio.sleep(1)
                    continue
                
                # Check if queue is empty
                if not self.queue:
                    if not self.active:
                        self.processing = False
                        break
                    await asyncio.sleep(1)
                    continue
                
                # Get next task
                task = self.queue.pop(0)
                task.status = 'downloading'
                task.started_at = datetime.now()
                self.active[task.task_id] = task
                
                logger.info(f"Starting task {task.task_id}")
            
            # Start download in background
            asyncio.create_task(self._execute_download(task))
            
            await asyncio.sleep(0.1)
    
    async def _execute_download(self, task: DownloadTask):
        """Execute download task"""
        try:
            from plugins.downloader import download_file
            
            # Progress callback
            async def progress_callback(downloaded, total, speed):
                task.downloaded = downloaded
                task.total_size = total
                task.speed = speed
                task.progress = (downloaded / total * 100) if total > 0 else 0
            
            # Download file
            result = await download_file(
                url=task.url,
                progress_callback=progress_callback,
                message=task.message
            )
            
            async with self.lock:
                if task.status == 'cancelled':
                    # Task was cancelled
                    del self.active[task.task_id]
                    return
                
                if result and result.get('success'):
                    task.status = 'completed'
                    task.filename = result.get('filename')
                    task.completed_at = datetime.now()
                    self.completed[task.task_id] = task
                    logger.info(f"Task {task.task_id} completed: {task.filename}")
                else:
                    task.status = 'failed'
                    task.error = result.get('error', 'Unknown error') if result else 'Download failed'
                    self.completed[task.task_id] = task
                    logger.error(f"Task {task.task_id} failed: {task.error}")
                
                del self.active[task.task_id]
        
        except Exception as e:
            logger.error(f"Task {task.task_id} exception: {e}")
            async with self.lock:
                task.status = 'failed'
                task.error = str(e)
                self.completed[task.task_id] = task
                if task.task_id in self.active:
                    del self.active[task.task_id]
    
    def get_active_downloads(self) -> Dict:
        """Get active downloads"""
        return self.active.copy()

    def get_stats(self) -> Dict:
        """Get queue statistics"""
        return {
            'queued': len(self.queue),
            'active': len(self.active),
            'completed': len(self.completed),
            'max_concurrent': self.max_concurrent
        }
    
    async def clear_completed(self, user_id: Optional[int] = None):
        """Clear completed tasks"""
        async with self.lock:
            if user_id:
                self.completed = {
                    tid: task for tid, task in self.completed.items()
                    if task.user_id != user_id
                }
            else:
                self.completed.clear()

# Global queue instance
from config import Config as _QCFG
download_queue = DownloadQueue(max_concurrent=int(getattr(_QCFG, "BIMBO_MAX_CONCURRENT_TASKS", 2)))

async def add_to_queue(task_id: str, user_id: int, url: str, 
                       message: Message, priority: int = 0) -> int:
    """Add download to queue"""
    task = DownloadTask(task_id, user_id, url, message, priority)
    return await download_queue.add_task(task)

async def remove_from_queue(task_id: str) -> bool:
    """Remove download from queue"""
    return await download_queue.remove_task(task_id)

async def get_queue_position(task_id: str) -> Optional[int]:
    """Get queue position"""
    return await download_queue.get_queue_position(task_id)

async def get_task_status(task_id: str) -> Optional[Dict]:
    """Get task status"""
    task = await download_queue.get_task(task_id)
    return task.to_dict() if task else None

async def get_user_queue(user_id: int) -> Dict[str, List[Dict]]:
    """Get user's queue"""
    tasks = await download_queue.get_user_tasks(user_id)
    return {
        'queued': [t.to_dict() for t in tasks['queued']],
        'active': [t.to_dict() for t in tasks['active']],
        'completed': [t.to_dict() for t in tasks['completed']]
    }

def get_queue_stats() -> Dict:
    """Get queue statistics"""
    return download_queue.get_stats()

async def clear_user_completed(user_id: int):
    """Clear user's completed tasks"""
    await download_queue.clear_completed(user_id)
