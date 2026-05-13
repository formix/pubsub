Welcome to formix-pubsub's documentation!
==========================================

A serverless, zero-dependency publish-subscribe library for Python interprocess communication.

Unlike traditional pub/sub systems that require a broker or server process, **formix-pubsub**
uses kernel FIFO named pipes and the shared-memory filesystem (``/dev/shm`` on Linux) for
message routing. There is nothing to install, start, or configure beyond the package itself.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   quickstart
   api
   examples

Features
--------

* **Serverless** — no broker, no server, no external service required
* **Zero dependencies** — pure Python, standard library only
* **Interprocess communication** designed for true parallelism across separate processes
* **Topic-based routing** with wildcard support (``=`` for single word, ``+`` for multiple words)
* **Multiple subscribers** can listen to the same topic independently
* **Message persistence** via file system until consumed
* **Non-blocking fetch** using FIFO queues
* **Automatic cleanup** of stale channels from terminated processes
* **Context manager support** for resource cleanup

Installation
------------

.. code-block:: bash

   pip install formix-pubsub

Requires Python 3.11 or later.

Quick Example
-------------

The core use case is communication between separate processes. Create two files:

**subscriber.py**

.. code-block:: python

   from pubsub import Channel, subscribe

   channel = Channel(topic="greetings")

   with channel:
       def on_message(msg):
           print(f"Received: {msg.content.decode()}")

       # Blocks until terminated with Ctrl+C or SIGTERM
       subscribe(channel, on_message)

**publisher.py**

.. code-block:: python

   from pubsub import publish

   count = publish("greetings", b"Hello from another process!")
   print(f"Published to {count} subscriber(s)")

Run the subscriber first, then the publisher in a second terminal:

.. code-block:: bash

   # Terminal 1
   python subscriber.py

   # Terminal 2
   python publisher.py

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
