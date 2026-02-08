Quick Start Guide
=================

Installation
------------

Install formix-pubsub using pip:

.. code-block:: bash

   pip install formix-pubsub

Basic Usage
-----------

Basic Publish-Subscribe
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from pubsub import Channel, publish, subscribe

   # Create a channel for a specific topic
   channel = Channel(topic="news.sports")

   with channel:
       # Publish to a concrete topic
       count = publish("news.sports", b"Team wins championship!")
       print(f"Published to {count} channel(s)")

       # Subscribe with a callback
       def handle_message(message):
           print(f"Received: {message.content.decode()}")

       subscribe(channel, handle_message, timeout_seconds=5.0)

Fetching Messages Manually
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from pubsub import Channel, publish, fetch

   channel = Channel(topic="alerts")

   with channel:
       # Publish some messages
       publish("alerts", b"System starting")
       publish("alerts", b"All systems operational")

       # Fetch messages one at a time
       message = fetch(channel)
       while message:
           print(f"{message.topic}: {message.content.decode()}")
           message = fetch(channel)

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

       subscribe(channel, handle_message, timeout_seconds=10.0)

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
           subscribe(channel, handle, timeout_seconds=5.0)

   def subscriber2(channel):
       with channel:
           def handle(msg):
               print(f"Subscriber 2: {msg.content.decode()}")
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
5. **Handle message timeouts gracefully** - Subscribe operations can timeout
