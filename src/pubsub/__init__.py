"""
PubSub - A Python publish-subscribe messaging library.

This library provides a simple and efficient way to implement 
publish-subscribe patterns in Python applications.
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from .publisher import Publisher
from .subscriber import Subscriber
from .message import Message
from .exceptions import PubSubError, TopicNotFoundError, SubscriberError

__all__ = [
    "Publisher",
    "Subscriber", 
    "Message",
    "PubSubError",
    "TopicNotFoundError",
    "SubscriberError",
]