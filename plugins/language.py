from typing import Dict

# Language translations
TRANSLATIONS = {
    'en': {
        # General
        'welcome': 'Welcome to BIMBO Bot!',
        'help': 'How can I help you?',
        'error': 'An error occurred',
        'loading': 'Loading...',
        'processing': 'Processing...',
        'success': 'Success!',
        'failed': 'Failed!',
        'cancel': 'Cancel',
        'close': 'Close',
        
        # Download
        'download_start': 'Starting download...',
        'download_progress': 'Downloading',
        'download_complete': 'Download complete!',
        'download_failed': 'Download failed',
        'download_cancelled': 'Download cancelled',
        
        # Upload
        'upload_start': 'Starting upload...',
        'upload_progress': 'Uploading',
        'upload_complete': 'Upload complete!',
        'upload_failed': 'Upload failed',
        
        # Queue
        'queue_position': 'Your position in queue: #{position}',
        'queue_empty': 'Queue is empty',
        'queue_full': 'Queue is full, please try again later',
        
        # Quota
        'quota_exceeded': 'Daily quota exceeded! You can download {remaining} more files today.',
        'quota_remaining': 'Remaining downloads today: {remaining}',
        'quota_reset': 'Quota resets at midnight',
        
        # Premium
        'premium_required': 'This feature requires Premium membership',
        'premium_active': 'Premium membership active',
        'premium_expired': 'Premium membership expired',
        
        # Torrent
        'torrent_start': 'Starting torrent download...',
        'torrent_seeding': 'Seeding torrent',
        'torrent_no_peers': 'No peers found',
        
        # Errors
        'invalid_url': 'Invalid URL',
        'file_not_found': 'File not found',
        'permission_denied': 'Permission denied',
        'network_error': 'Network error',
        
        # Admin
        'admin_only': 'This command is for admins only',
        'user_banned': 'User has been banned',
        'user_unbanned': 'User has been unbanned',
        
        # Stats
        'system_stats': 'System Statistics',
        'cpu_usage': 'CPU Usage',
        'ram_usage': 'RAM Usage',
        'disk_usage': 'Disk Usage',
        'uptime': 'Uptime',
    },
    
    'hi': {
        # General
        'welcome': 'BIMBO Bot में आपका स्वागत है!',
        'help': 'मैं आपकी कैसे मदद कर सकता हूँ?',
        'error': 'एक त्रुटि हुई',
        'loading': 'लोड हो रहा है...',
        'processing': 'प्रोसेस हो रहा है...',
        'success': 'सफल!',
        'failed': 'विफल!',
        'cancel': 'रद्द करें',
        'close': 'बंद करें',
        
        # Download
        'download_start': 'डाउनलोड शुरू हो रहा है...',
        'download_progress': 'डाउनलोड हो रहा है',
        'download_complete': 'डाउनलोड पूर्ण!',
        'download_failed': 'डाउनलोड विफल',
        'download_cancelled': 'डाउनलोड रद्द किया गया',
        
        # Upload
        'upload_start': 'अपलोड शुरू हो रहा है...',
        'upload_progress': 'अपलोड हो रहा है',
        'upload_complete': 'अपलोड पूर्ण!',
        'upload_failed': 'अपलोड विफल',
        
        # Queue
        'queue_position': 'कतार में आपकी स्थिति: #{position}',
        'queue_empty': 'कतार खाली है',
        'queue_full': 'कतार भरी है, कृपया बाद में प्रयास करें',
        
        # Quota
        'quota_exceeded': 'दैनिक कोटा पार हो गया! आज आप {remaining} और फ़ाइलें डाउनलोड कर सकते हैं।',
        'quota_remaining': 'आज शेष डाउनलोड: {remaining}',
        'quota_reset': 'कोटा मध्यरात्रि को रीसेट होता है',
        
        # Premium
        'premium_required': 'इस सुविधा के लिए प्रीमियम सदस्यता आवश्यक है',
        'premium_active': 'प्रीमियम सदस्यता सक्रिय है',
        'premium_expired': 'प्रीमियम सदस्यता समाप्त हो गई',
        
        # Torrent
        'torrent_start': 'टोरेंट डाउनलोड शुरू हो रहा है...',
        'torrent_seeding': 'टोरेंट सीडिंग',
        'torrent_no_peers': 'कोई पीयर नहीं मिला',
        
        # Errors
        'invalid_url': 'अमान्य URL',
        'file_not_found': 'फ़ाइल नहीं मिली',
        'permission_denied': 'अनुमति अस्वीकृत',
        'network_error': 'नेटवर्क त्रुटि',
        
        # Admin
        'admin_only': 'यह कमांड केवल एडमिन के लिए है',
        'user_banned': 'उपयोगकर्ता को प्रतिबंधित कर दिया गया है',
        'user_unbanned': 'उपयोगकर्ता को प्रतिबंध मुक्त कर दिया गया है',
        
        # Stats
        'system_stats': 'सिस्टम आँकड़े',
        'cpu_usage': 'CPU उपयोग',
        'ram_usage': 'RAM उपयोग',
        'disk_usage': 'डिस्क उपयोग',
        'uptime': 'अपटाइम',
    }
}

# Default language
DEFAULT_LANGUAGE = 'en'

# User language preferences (stored in memory, should be in database for production)
user_languages: Dict[int, str] = {}

def set_user_language(user_id: int, language: str):
    """Set user's preferred language"""
    if language in TRANSLATIONS:
        user_languages[user_id] = language
        return True
    return False

def get_user_language(user_id: int) -> str:
    """Get user's preferred language"""
    return user_languages.get(user_id, DEFAULT_LANGUAGE)

def t(key: str, user_id: int = None, **kwargs) -> str:
    """Get translated text"""
    lang = get_user_language(user_id) if user_id else DEFAULT_LANGUAGE
    text = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANGUAGE]).get(key, key)
    
    # Format with kwargs
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    
    return text

def get_available_languages() -> Dict[str, str]:
    """Get available languages"""
    return {
        'en': 'English',
        'hi': 'हिंदी (Hindi)'
    }

def get_language_name(lang_code: str) -> str:
    """Get language name"""
    languages = get_available_languages()
    return languages.get(lang_code, 'Unknown')

# Aliases for backward compatibility (used by plugins/commands.py)
set_language = set_user_language
LANGUAGES = get_available_languages()
