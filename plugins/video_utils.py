import os
import time
import asyncio
import logging
from typing import Optional, Dict
import subprocess

logger = logging.getLogger(__name__)

class VideoConverter:
    def __init__(self):
        self.supported_formats = ['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv']
        self.supported_codecs = {
            'video': ['h264', 'h265', 'vp9', 'av1'],
            'audio': ['aac', 'mp3', 'opus', 'vorbis']
        }
    
    async def convert_video(self, input_path: str, output_format: str = 'mp4',
                           video_codec: str = 'h264', audio_codec: str = 'aac',
                           quality: str = 'medium', progress_callback=None) -> Optional[str]:
        """Convert video to specified format"""
        
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            return None
        
        # Generate output path - use temp file to avoid ffmpeg "same as input" error
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(os.path.dirname(input_path), f"{base_name}_converted_{int(time.time())}.{output_format}")
        # If same as input, add suffix
        if output_path == input_path:
            output_path = os.path.join(os.path.dirname(input_path), f"{base_name}_converted.{output_format}")
        
        # Quality presets
        quality_presets = {
            'low': {'crf': '28', 'preset': 'ultrafast'},
            'medium': {'crf': '23', 'preset': 'medium'},
            'high': {'crf': '18', 'preset': 'slow'},
            'ultra': {'crf': '15', 'preset': 'veryslow'}
        }
        
        preset = quality_presets.get(quality, quality_presets['medium'])
        
        # Build FFmpeg command
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264' if video_codec == 'h264' else f'lib{video_codec}',
            '-crf', preset['crf'],
            '-preset', preset['preset'],
            '-c:a', audio_codec,
            '-b:a', '192k',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]
        
        try:
            logger.info(f"Converting video: {input_path} -> {output_path}")
            
            # Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Monitor progress
            if progress_callback:
                duration = await self.get_video_duration(input_path)
                await self._monitor_progress(process, duration, progress_callback)
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Video conversion successful: {output_path}")
                return output_path
            else:
                logger.error(f"Video conversion failed: {stderr.decode()}")
                return None
        
        except Exception as e:
            logger.error(f"Video conversion error: {e}")
            return None
    
    async def get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return float(stdout.decode().strip())
            return 0
        
        except Exception as e:
            logger.error(f"Get duration error: {e}")
            return 0
    
    async def _monitor_progress(self, process, duration: float, callback):
        """Monitor FFmpeg progress"""
        import re
        
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            
            line = line.decode('utf-8', errors='ignore')
            
            # Parse time from FFmpeg output
            time_match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
            if time_match and duration > 0:
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                seconds = float(time_match.group(3))
                
                current_time = hours * 3600 + minutes * 60 + seconds
                progress = (current_time / duration) * 100
                
                await callback(progress, current_time, duration)
    
    async def extract_audio(self, video_path: str, audio_format: str = 'mp3',
                           bitrate: str = '192k') -> Optional[str]:
        """Extract audio from video"""
        
        if not os.path.exists(video_path):
            return None
        
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        output_path = os.path.join(os.path.dirname(video_path), f"{base_name}.{audio_format}")
        
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vn',  # No video
            '-acodec', 'libmp3lame' if audio_format == 'mp3' else audio_format,
            '-ab', bitrate,
            '-y',
            output_path
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return output_path
            else:
                logger.error(f"Audio extraction failed: {stderr.decode()}")
                return None
        
        except Exception as e:
            logger.error(f"Audio extraction error: {e}")
            return None
    
    async def get_video_info(self, video_path: str) -> Optional[Dict]:
        """Get video information"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'stream=codec_name,width,height,duration,bit_rate',
                '-show_entries', 'format=duration,size,bit_rate',
                '-of', 'json',
                video_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                import json
                return json.loads(stdout.decode())
            return None
        
        except Exception as e:
            logger.error(f"Get video info error: {e}")
            return None


class ScreenshotGenerator:
    def __init__(self):
        pass
    
    async def generate_screenshot(self, video_path: str, timestamp: float = None,
                                 output_path: str = None, quality: int = 2) -> Optional[str]:
        """Generate screenshot from video"""
        
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return None
        
        # Get video duration if timestamp not provided
        if timestamp is None:
            converter = VideoConverter()
            duration = await converter.get_video_duration(video_path)
            timestamp = duration * 0.1  # 10% into the video
        
        # Generate output path if not provided
        if not output_path:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(
                os.path.dirname(video_path),
                f"{base_name}_screenshot_{int(timestamp)}.jpg"
            )
        
        # Build FFmpeg command
        cmd = [
            'ffmpeg',
            '-ss', str(timestamp),
            '-i', video_path,
            '-vframes', '1',
            '-q:v', str(quality),
            '-y',
            output_path
        ]
        
        try:
            logger.info(f"Generating screenshot at {timestamp}s: {output_path}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and os.path.exists(output_path):
                logger.info(f"Screenshot generated: {output_path}")
                return output_path
            else:
                logger.error(f"Screenshot generation failed: {stderr.decode()}")
                return None
        
        except Exception as e:
            logger.error(f"Screenshot generation error: {e}")
            return None
    
    async def generate_multiple_screenshots(self, video_path: str, count: int = 4,
                                           output_dir: str = None) -> list:
        """Generate multiple screenshots from video"""
        
        if not os.path.exists(video_path):
            return []
        
        converter = VideoConverter()
        duration = await converter.get_video_duration(video_path)
        
        if duration <= 0:
            return []
        
        # Calculate timestamps
        interval = duration / (count + 1)
        timestamps = [interval * (i + 1) for i in range(count)]
        
        # Generate screenshots
        screenshots = []
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        
        if not output_dir:
            output_dir = os.path.dirname(video_path)
        
        for i, timestamp in enumerate(timestamps):
            output_path = os.path.join(output_dir, f"{base_name}_screenshot_{i+1}.jpg")
            screenshot = await self.generate_screenshot(video_path, timestamp, output_path)
            
            if screenshot:
                screenshots.append(screenshot)
        
        return screenshots
    
    async def generate_thumbnail_grid(self, video_path: str, output_path: str = None,
                                     grid_size: tuple = (2, 2)) -> Optional[str]:
        """Generate thumbnail grid from video"""
        
        screenshots = await self.generate_multiple_screenshots(
            video_path,
            count=grid_size[0] * grid_size[1]
        )
        
        if not screenshots:
            return None
        
        try:
            from PIL import Image
            
            # Open all screenshots
            images = [Image.open(img) for img in screenshots]
            
            # Calculate grid dimensions
            width = images[0].width
            height = images[0].height
            
            grid_width = width * grid_size[0]
            grid_height = height * grid_size[1]
            
            # Create grid
            grid = Image.new('RGB', (grid_width, grid_height))
            
            for i, img in enumerate(images):
                x = (i % grid_size[0]) * width
                y = (i // grid_size[0]) * height
                grid.paste(img, (x, y))
                img.close()
            
            # Save grid
            if not output_path:
                base_name = os.path.splitext(os.path.basename(video_path))[0]
                output_path = os.path.join(
                    os.path.dirname(video_path),
                    f"{base_name}_grid.jpg"
                )
            
            grid.save(output_path, quality=90)
            grid.close()
            
            # Cleanup individual screenshots
            for screenshot in screenshots:
                os.remove(screenshot)
            
            return output_path
        
        except Exception as e:
            logger.error(f"Thumbnail grid error: {e}")
            return None


# Global instances
video_converter = VideoConverter()
screenshot_generator = ScreenshotGenerator()

# Convenience functions
async def convert_video(input_path: str, output_format: str = 'mp4', **kwargs) -> Optional[str]:
    """Convert video"""
    return await video_converter.convert_video(input_path, output_format, **kwargs)

async def extract_audio(video_path: str, **kwargs) -> Optional[str]:
    """Extract audio from video"""
    return await video_converter.extract_audio(video_path, **kwargs)

async def get_video_info(video_path: str) -> Optional[Dict]:
    """Get video information"""
    return await video_converter.get_video_info(video_path)

async def generate_screenshot(video_path: str, **kwargs) -> Optional[str]:
    """Generate screenshot"""
    return await screenshot_generator.generate_screenshot(video_path, **kwargs)

async def generate_multiple_screenshots(video_path: str, **kwargs) -> list:
    """Generate multiple screenshots"""
    return await screenshot_generator.generate_multiple_screenshots(video_path, **kwargs)

async def generate_thumbnail_grid(video_path: str, **kwargs) -> Optional[str]:
    """Generate thumbnail grid"""
    return await screenshot_generator.generate_thumbnail_grid(video_path, **kwargs)


async def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds (standalone helper for imports)."""
    return await video_converter.get_video_duration(video_path)


async def get_video_width_height(video_path: str):
    """Return (width, height, duration) using ffprobe."""
    try:
        import json as _json
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", video_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        d = _json.loads(out.decode("utf-8", "ignore") or "{}")
        streams = d.get("streams", [{}])
        v = streams[0] if streams else {}
        fmt = d.get("format", {})
        w = int(v.get("width") or 0)
        h = int(v.get("height") or 0)
        dur = float(fmt.get("duration") or 0)
        return w, h, dur
    except Exception:
        return 0, 0, 0
