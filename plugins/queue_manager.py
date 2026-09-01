"""
Industrial-Grade Queue Manager for BIMBO Bot
Features: Position tracking, ETA calculation, priority queue, status management
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import defaultdict
import json
import os

logger = logging.getLogger(__name__)

class DownloadTask:
    """Represents a single download task"""
    
    def __init__(self, task_id: str, user_id: int, url: str, filename: str, 
                 priority: int = 0, quality: str = "best"):
        self.task_id = task_id
        self.user_id = user_id
        self.url = url
        self.filename = filename
        self.priority = priority
        self.quality = quality
        self.status = "queued"  # queued, processing, completed, failed, paused
        self.position = 0
        self.created_at = time.time()
        self.started_at = None
        self.completed_at = None
        self.progress = 0
        self.error_message = None
        self.eta = None
        
    def to_dict(self):
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "url": self.url,
            "filename": self.filename,
            "priority": self.priority,
            "quality": self.quality,
            "status": self.status,
            "position": self.position,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "error_message": self.error_message,
            "eta": self.eta
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        task = cls(
            task_id=data["task_id"],
            user_id=data["user_id"],
            url=data["url"],
            filename=data["filename"],
            priority=data.get("priority", 0),
            quality=data.get("quality", "best")
        )
        task.status = data.get("status", "queued")
        task.position = data.get("position", 0)
        task.created_at = data.get("created_at", time.time())
        task.started_at = data.get("started_at")
        task.completed_at = data.get("completed_at")
        task.progress = data.get("progress", 0)
        task.error_message = data.get("error_message")
        task.eta = data.get("eta")
        return task


class QueueManager:
    """Industrial-grade queue manager with position tracking and ETA"""
    
    def __init__(self, max_concurrent: int = 3, save_interval: int = 30):
        self.max_concurrent = max_concurrent
        self.save_interval = save_interval
        self.queue: List[DownloadTask] = []
        self.active_downloads: Dict[str, DownloadTask] = {}
        self.completed_downloads: List[DownloadTask] = []
        self.failed_downloads: List[DownloadTask] = []
        self.task_counter = 0
        self.save_file = "queue_state.json"
        
        # Load saved state if exists
        self._load_state()
        
        # Start auto-save task
        asyncio.create_task(self._auto_save())
    
    def _generate_task_id(self) -> str:
        """Generate unique task ID"""
        self.task_counter += 1
        return f"task_{int(time.time())}_{self.task_counter}"
    
    def _load_state(self):
        """Load queue state from file"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'r') as f:
                    data = json.load(f)
                    self.queue = [DownloadTask.from_dict(t) for t in data.get("queue", [])]
                    self.active_downloads = {k: DownloadTask.from_dict(v) for k, v in data.get("active", {}).items()}
                    self.completed_downloads = [DownloadTask.from_dict(t) for t in data.get("completed", [])]
                    self.failed_downloads = [DownloadTask.from_dict(t) for t in data.get("failed", [])]
                    self.task_counter = data.get("task_counter", 0)
                    logger.info(f"Loaded queue state: {len(self.queue)} queued, {len(self.active_downloads)} active")
        except Exception as e:
            logger.error(f"Failed to load queue state: {e}")
    
    def _save_state(self):
        """Save queue state to file"""
        try:
            data = {
                "queue": [t.to_dict() for t in self.queue],
                "active": {k: v.to_dict() for k, v in self.active_downloads.items()},
                "completed": [t.to_dict() for t in self.completed_downloads[-100:]],  # Keep last 100
                "failed": [t.to_dict() for t in self.failed_downloads[-100:]],
                "task_counter": self.task_counter
            }
            with open(self.save_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save queue state: {e}")
    
    async def _auto_save(self):
        """Auto-save queue state periodically"""
        while True:
            await asyncio.sleep(self.save_interval)
            self._save_state()
    
    def add_task(self, user_id: int, url: str, filename: str, 
                 priority: int = 0, quality: str = "best") -> DownloadTask:
        """Add new task to queue"""
        task_id = self._generate_task_id()
        task = DownloadTask(
            task_id=task_id,
            user_id=user_id,
            url=url,
            filename=filename,
            priority=priority,
            quality=quality
        )
        
        # Add to queue and sort by priority
        self.queue.append(task)
        self._update_positions()
        
        logger.info(f"Task {task_id} added to queue for user {user_id}")
        return task
    
    def _update_positions(self):
        """Update positions for all queued tasks"""
        # Sort by priority (higher first) then by creation time
        self.queue.sort(key=lambda t: (-t.priority, t.created_at))
        
        # Update positions
        for idx, task in enumerate(self.queue, 1):
            task.position = idx
    
    def get_next_task(self) -> Optional[DownloadTask]:
        """Get next task to process"""
        if len(self.active_downloads) >= self.max_concurrent:
            return None
        
        if not self.queue:
            return None
        
        task = self.queue.pop(0)
        task.status = "processing"
        task.started_at = time.time()
        self.active_downloads[task.task_id] = task
        
        # Update remaining positions
        self._update_positions()
        
        return task
    
    def update_progress(self, task_id: str, progress: float):
        """Update task progress"""
        if task_id in self.active_downloads:
            self.active_downloads[task_id].progress = progress
            
            # Calculate ETA
            task = self.active_downloads[task_id]
            if task.started_at and progress > 0:
                elapsed = time.time() - task.started_at
                if progress < 100:
                    total_time = (elapsed / progress) * 100
                    remaining = total_time - elapsed
                    task.eta = int(remaining)
    
    def complete_task(self, task_id: str):
        """Mark task as completed"""
        if task_id in self.active_downloads:
            task = self.active_downloads.pop(task_id)
            task.status = "completed"
            task.completed_at = time.time()
            task.progress = 100
            self.completed_downloads.append(task)
            logger.info(f"Task {task_id} completed")
    
    def fail_task(self, task_id: str, error: str):
        """Mark task as failed"""
        if task_id in self.active_downloads:
            task = self.active_downloads.pop(task_id)
            task.status = "failed"
            task.completed_at = time.time()
            task.error_message = error
            self.failed_downloads.append(task)
            logger.error(f"Task {task_id} failed: {error}")
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a queued or active task"""
        # Check in queue
        for idx, task in enumerate(self.queue):
            if task.task_id == task_id:
                self.queue.pop(idx)
                self._update_positions()
                logger.info(f"Task {task_id} cancelled from queue")
                return True
        
        # Check in active downloads
        if task_id in self.active_downloads:
            task = self.active_downloads.pop(task_id)
            task.status = "failed"
            task.error_message = "Cancelled by user"
            self.failed_downloads.append(task)
            logger.info(f"Task {task_id} cancelled from active downloads")
            return True
        
        return False
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status"""
        return {
            "queued": len(self.queue),
            "active": len(self.active_downloads),
            "completed": len(self.completed_downloads),
            "failed": len(self.failed_downloads),
            "max_concurrent": self.max_concurrent
        }
    
    def get_user_tasks(self, user_id: int) -> Dict[str, List[DownloadTask]]:
        """Get all tasks for a specific user"""
        return {
            "queued": [t for t in self.queue if t.user_id == user_id],
            "active": [t for t in self.active_downloads.values() if t.user_id == user_id],
            "completed": [t for t in self.completed_downloads if t.user_id == user_id],
            "failed": [t for t in self.failed_downloads if t.user_id == user_id]
        }
    
    def get_task_info(self, task_id: str) -> Optional[DownloadTask]:
        """Get task information"""
        # Check queue
        for task in self.queue:
            if task.task_id == task_id:
                return task
        
        # Check active
        if task_id in self.active_downloads:
            return self.active_downloads[task_id]
        
        # Check completed
        for task in self.completed_downloads:
            if task.task_id == task_id:
                return task
        
        # Check failed
        for task in self.failed_downloads:
            if task.task_id == task_id:
                return task
        
        return None
    
    def pause_task(self, task_id: str) -> bool:
        """Pause an active task"""
        if task_id in self.active_downloads:
            task = self.active_downloads[task_id]
            task.status = "paused"
            logger.info(f"Task {task_id} paused")
            return True
        return False
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task"""
        for task in self.queue:
            if task.task_id == task_id and task.status == "paused":
                task.status = "queued"
                logger.info(f"Task {task_id} resumed")
                return True
        return False
    
    def clear_completed(self):
        """Clear completed downloads"""
        count = len(self.completed_downloads)
        self.completed_downloads.clear()
        logger.info(f"Cleared {count} completed tasks")
    
    def clear_failed(self):
        """Clear failed downloads"""
        count = len(self.failed_downloads)
        self.failed_downloads.clear()
        logger.info(f"Cleared {count} failed tasks")


# Global queue manager instance
queue_manager = QueueManager(max_concurrent=3, save_interval=30)
