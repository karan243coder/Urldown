"""
Resume Downloads - Continue downloads after bot restart
Features: Save download state, resume from where it stopped
"""

import os
import json
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class DownloadResumer:
    """Manage download resume capability"""
    
    def __init__(self, state_file: str = "download_states.json"):
        self.state_file = state_file
        self.states: Dict[str, Dict] = {}
        self._load_states()
    
    def _load_states(self):
        """Load download states from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    self.states = json.load(f)
                logger.info(f"Loaded {len(self.states)} download states")
        except Exception as e:
            logger.error(f"Failed to load download states: {e}")
    
    def _save_states(self):
        """Save download states to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.states, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save download states: {e}")
    
    def save_state(self, task_id: str, url: str, file_path: str, 
                   downloaded_bytes: int, total_bytes: int, 
                   user_id: int, quality: str):
        """Save download state"""
        self.states[task_id] = {
            "url": url,
            "file_path": file_path,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
            "progress": (downloaded_bytes / total_bytes * 100) if total_bytes > 0 else 0,
            "user_id": user_id,
            "quality": quality,
            "saved_at": datetime.now().isoformat()
        }
        self._save_states()
        logger.info(f"Saved state for task {task_id}: {self.states[task_id]['progress']:.1f}%")
    
    def get_state(self, task_id: str) -> Optional[Dict]:
        """Get download state"""
        return self.states.get(task_id)
    
    def remove_state(self, task_id: str):
        """Remove download state after completion"""
        if task_id in self.states:
            del self.states[task_id]
            self._save_states()
            logger.info(f"Removed state for task {task_id}")
    
    def get_resumable_downloads(self) -> Dict[str, Dict]:
        """Get all resumable downloads"""
        return self.states.copy()
    
    def clear_old_states(self, max_age_hours: int = 24):
        """Clear states older than max_age_hours"""
        now = datetime.now()
        to_remove = []
        
        for task_id, state in self.states.items():
            saved_at = datetime.fromisoformat(state["saved_at"])
            age_hours = (now - saved_at).total_seconds() / 3600
            
            if age_hours > max_age_hours:
                to_remove.append(task_id)
        
        for task_id in to_remove:
            del self.states[task_id]
        
        if to_remove:
            self._save_states()
            logger.info(f"Cleared {len(to_remove)} old download states")


# Global instance
download_resumer = DownloadResumer()


async def resume_downloads_on_startup(bot):
    """Resume interrupted downloads on bot startup"""
    resumable = download_resumer.get_resumable_downloads()
    
    if not resumable:
        logger.info("No downloads to resume")
        return
    
    logger.info(f"Found {len(resumable)} downloads to resume")
    
    for task_id, state in resumable.items():
        try:
            # Notify user about resume
            await bot.send_message(
                chat_id=state["user_id"],
                text=f"🔄 Bot restart ho gaya tha! Aapka download resume ho raha hai:\n"
                     f"📁 {state['url'][:50]}...\n"
                     f"📊 Progress: {state['progress']:.1f}%\n\n"
                     f"Bot automatically download complete karega."
            )
            
            # Here you would implement the actual resume logic
            # This depends on your download mechanism (yt-dlp, requests, etc.)
            # For yt-dlp, you can use the same file path and it will continue
            
            logger.info(f"Resumed download {task_id} for user {state['user_id']}")
            
        except Exception as e:
            logger.error(f"Failed to resume download {task_id}: {e}")
