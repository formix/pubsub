"""
PubSub - A Python publish-subscribe messaging library.

This library provides a simple and efficient way to implement 
publish-subscribe patterns in Python applications.
"""

__version__ = "1.0.0"
__author__ = "Jean-Philippe Gravel"
__email__ = "jeanphilippe.gravel@gmail.com"

from .message import Message
from .channel import Channel
from .pubsub import publish, fetch, subscribe

__all__ = [
    "Message",
    "Channel",
    "publish",
    "fetch", 
    "subscribe"
]