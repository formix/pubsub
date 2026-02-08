Welcome to formix-pubsub's documentation!
==========================================

A lightweight, serverless publish-subscribe messaging system for Python (and other languages) 
interprocess communications.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   quickstart
   api
   examples

Features
--------

* **Interprocess communication** designed for true parallelism across separate processes
* **Topic-based routing** with wildcard support (``=`` for single word, ``+`` for multiple words)
* **Multiple subscribers** can listen to the same topic independently
* **Message persistence** via file system until consumed
* **Non-blocking operations** using FIFO queues
* **Context manager support** for automatic resource cleanup
* **Thread-safe** operations as a bonus (though designed primarily for separate processes)

Design Philosophy
-----------------

This library is designed for **interprocess communication**. Each subscriber typically runs in 
its own process, enabling true parallel execution without GIL limitations. While thread-safe 
for convenience, the real power comes from process-based parallelism.

Installation
------------

.. code-block:: bash

   pip install formix-pubsub

Quick Example
-------------

.. code-block:: python

   from pubsub import Channel, publish, subscribe

   # Create a channel for a specific topic
   channel = Channel(topic="news.sports")

   with channel:
       # Publish a message
       publish("news.sports", b"Team wins championship!")
       
       # Subscribe with a callback
       def handle_message(message):
           print(f"Received: {message.content.decode()}")
       
       subscribe(channel, handle_message, timeout_seconds=5.0)

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
