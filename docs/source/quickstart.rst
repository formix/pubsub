Quick Start Guide
=================

Installation
------------

Install formix-pubsub using pip:

.. code-block:: bash

   pip install formix-pubsub

Requires Python 3.11 or later.

Basic Usage
-----------

Publish & Subscribe Across Processes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The core use case is communication between separate processes. Create two files:

**subscriber.py**

.. code-block:: python

   from pubsub import Channel, subscribe

   channel = Channel(topic="greetings")

   with channel:
       def on_message(msg):
           print(f"Received: {msg.content.decode()}")

       # Blocks and listens until terminated with Ctrl+C or SIGTERM
       subscribe(channel, on_message)

**publisher.py**

.. code-block:: python

   from pubsub import publish

   count = publish("greetings", b"Hello from another process!")
   print(f"Published to {count} subscriber(s)")

Run the subscriber first in one terminal, then the publisher in a second:

.. code-block:: bash

   # Terminal 1
   python subscriber.py

   # Terminal 2
   python publisher.py

The subscriber prints ``Received: Hello from another process!`` and keeps listening.
Press ``Ctrl+C`` to stop it gracefully.

Non-Blocking Fetch
~~~~~~~~~~~~~~~~~~~

Use ``fetch()`` to poll for messages without blocking. It returns ``None`` immediately
when the queue is empty.

.. code-block:: python

   from pubsub import Channel, publish, fetch

   channel = Channel(topic="tasks")

   with channel:
       # Publish a few messages
       publish("tasks", b"task-1")
       publish("tasks", b"task-2")
       publish("tasks", b"task-3")

       # Poll for messages
       msg = fetch(channel)
       while msg is not None:
           print(f"Processing: {msg.content.decode()}")
           msg = fetch(channel)

       print("Queue empty, moving on.")

Wildcard Topics
~~~~~~~~~~~~~~~

Use wildcards to subscribe to multiple topics:

* ``=`` matches a single word
* ``+`` matches one or more words

.. code-block:: python

   from pubsub import Channel, publish, subscribe

   # Channels can use wildcards to subscribe to multiple topics
   channel = Channel(topic="news.=")  # Matches: news.sports, news.tech, news.world

   with channel:
       def handle_message(msg):
           print(f"[{msg.topic}] {msg.content.decode()}")

       # Listens indefinitely; terminate with SIGTERM/SIGINT
       subscribe(channel, handle_message)

   # Publish to concrete topics
   publish("news.sports", b"Game results")
   publish("news.tech", b"New release")

Multiple Subscribers
~~~~~~~~~~~~~~~~~~~~

Multiple subscribers can listen independently to the same topic:

.. code-block:: python

   from pubsub import Channel, publish, subscribe
   import threading

   topic = "broadcast"

   # Create two independent channels for the same topic
   channel1 = Channel(topic=topic)
   channel2 = Channel(topic=topic)

   def subscriber1(channel):
       with channel:
           def handle(msg):
               print(f"Subscriber 1: {msg.content.decode()}")
           # Use timeout for demo; in production, terminate via signal
           subscribe(channel, handle, timeout_seconds=5.0)

   def subscriber2(channel):
       with channel:
           def handle(msg):
               print(f"Subscriber 2: {msg.content.decode()}")
           # Use timeout for demo; in production, terminate via signal
           subscribe(channel, handle, timeout_seconds=5.0)

   # Start subscribers in separate threads (use processes for true parallelism)
   t1 = threading.Thread(target=subscriber1, args=(channel1,))
   t2 = threading.Thread(target=subscriber2, args=(channel2,))

   t1.start()
   t2.start()

   # Publish a message - both subscribers receive it
   publish(topic, b"Hello everyone!")

   t1.join()
   t2.join()

Context Managers
~~~~~~~~~~~~~~~~

Always use context managers to ensure proper cleanup:

.. code-block:: python

   from pubsub import Channel

   # Good - automatic cleanup
   with Channel(topic="example") as channel:
       # Use the channel
       pass

   # Alternative - manual cleanup
   channel = Channel(topic="example")
   try:
       # Use the channel
       pass
   finally:
       channel.close()

Best Practices
--------------

1. **Use separate processes for true parallelism** - The GIL won't limit your concurrency
2. **Always use context managers** - Ensures proper resource cleanup
3. **Publish to concrete topics** - Wildcards are only for subscribing
4. **Use meaningful topic hierarchies** - e.g., ``app.service.event``
5. **Terminate subscribers gracefully** - Use SIGTERM/SIGINT for clean shutdown; timeouts are optional for demos or time-bound operations
