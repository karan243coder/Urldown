# -*- coding: utf-8 -*-
"""
Direct connection handler for xHamster (no proxy)
Free proxies are useless in production - all dead/slow/blocked.
Direct connection from Koyeb is fastest and most reliable.
"""

import logging

logger = logging.getLogger(__name__)


def get_proxy_dict():
    """No proxy - return None for direct connection"""
    return None


def mark_proxy_failed(proxy):
    """No-op - no proxy system"""
    pass
