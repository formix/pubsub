Examples
========

This page contains practical examples of using formix-pubsub in real-world scenarios.

Event Broadcasting System
--------------------------

Create an event broadcasting system where multiple services listen for events:

.. code-block:: python

   # services/email_service.py
   from pubsub import Channel, subscribe
   import multiprocessing

   def email_service():
       channel = Channel(topic="events.user.+")

       with channel:
           def handle_user_event(msg):
               event_type = msg.topic.split('.')[-1]
               if event_type == "registered":
                   print(f"Sending welcome email for: {msg.content.decode()}")
               elif event_type == "deleted":
                   print(f"Sending goodbye email for: {msg.content.decode()}")

           print("Email service started")
           # Listens indefinitely; terminate process with SIGTERM/SIGINT for graceful shutdown
           subscribe(channel, handle_user_event)

   if __name__ == "__main__":
       email_service()

.. code-block:: python

   # services/analytics_service.py
   from pubsub import Channel, subscribe

   def analytics_service():
       channel = Channel(topic="events.user.+")

       with channel:
           def handle_user_event(msg):
               print(f"Logging analytics: {msg.topic} - {msg.content.decode()}")

           print("Analytics service started")
           # Listens indefinitely; terminate process with SIGTERM/SIGINT for graceful shutdown
           subscribe(channel, handle_user_event)

   if __name__ == "__main__":
       analytics_service()

.. code-block:: python

   # main.py
   from pubsub import publish
   import multiprocessing
   from services.email_service import email_service
   from services.analytics_service import analytics_service

   # Start services in separate processes
   email_proc = multiprocessing.Process(target=email_service)
   analytics_proc = multiprocessing.Process(target=analytics_service)

   email_proc.start()
   analytics_proc.start()

   # Wait a moment for services to start
   import time
   time.sleep(0.5)

   # Publish events
   publish("events.user.registered", b"user123")
   publish("events.user.deleted", b"user456")

   # Wait for services to process
   time.sleep(2)

   # Gracefully terminate services (sends SIGTERM/SIGINT)
   email_proc.terminate()
   analytics_proc.terminate()

   # Wait for processes to finish cleaning up
   email_proc.join(timeout=5)
   analytics_proc.join(timeout=5)

Logging Aggregator
------------------

Collect logs from multiple services:

.. code-block:: python

   # logger.py
   from pubsub import Channel, subscribe
   import datetime

   def log_aggregator():
       channel = Channel(topic="logs.+")

       with open("application.log", "a") as log_file:
           with channel:
               def handle_log(msg):
                   timestamp = datetime.datetime.now().isoformat()
                   level = msg.topic.split('.')[-1]
                   log_line = f"[{timestamp}] [{level.upper()}] {msg.content.decode()}\n"
                   log_file.write(log_line)
                   log_file.flush()
                   print(log_line.strip())

               print("Log aggregator started")
               # Listens indefinitely; terminate process with SIGTERM/SIGINT for graceful shutdown
               subscribe(channel, handle_log)

   if __name__ == "__main__":
       log_aggregator()

.. code-block:: python

   # In your application
   from pubsub import publish

   # Services can publish logs
   publish("logs.info", b"Application started")
   publish("logs.warning", b"Cache miss, rebuilding")
   publish("logs.error", b"Failed to connect to database")

Request-Response (RPC) Pattern
-------------------------------

For request-response workflows, use message headers to route replies back to the
caller. This example implements a multiply service with correlation IDs and timeout
handling.

**rpc_server.py**

.. code-block:: python

   # rpc_server.py
   from pubsub import Channel, subscribe, publish

   channel = Channel(topic="rpc.math.multiply")

   with channel:
       def handle_request(request):
           response_topic = request.headers.get("response-topic")
           correlation_id = request.headers.get("correlation-id")

           if not response_topic or not correlation_id:
               print("Malformed request (missing headers), skipping.")
               return

           # Parse operands from the payload
           a, b = request.content.decode().split(",")
           result = float(a) * float(b)

           # Publish the response back to the caller's private channel
           publish(
               response_topic,
               str(result).encode(),
               headers={"correlation-id": correlation_id},
           )
           print(f"[{correlation_id}] {a} * {b} = {result}")

       print("RPC server listening on 'rpc.math.multiply'...")
       subscribe(channel, handle_request)

**rpc_client.py**

.. code-block:: python

   # rpc_client.py
   import os
   import uuid

   from pubsub import Channel, publish, subscribe

   def rpc_multiply(a: float, b: float, timeout: float = 2.0) -> float:
       """Send a multiply request and wait for the response."""

       correlation_id = str(uuid.uuid4())
       result: dict = {}

       # Create a private response channel unique to this process
       response_topic = f"rpc.response.{os.getpid()}"
       response_channel = Channel(topic=response_topic)

       with response_channel:
           # Send the request with routing headers
           publish(
               "rpc.math.multiply",
               f"{a},{b}".encode(),
               headers={
                   "response-topic": response_topic,
                   "correlation-id": correlation_id,
               },
           )

           # Wait for the response using subscribe with a timeout
           def on_response(msg):
               if msg.headers.get("correlation-id") == correlation_id:
                   result["value"] = float(msg.content.decode())

           subscribe(response_channel, on_response, timeout_seconds=timeout)

       if "value" not in result:
           raise TimeoutError(
               f"No response received for correlation-id {correlation_id} "
               f"within {timeout}s"
           )

       return result["value"]


   if __name__ == "__main__":
       result = rpc_multiply(6, 7)
       print(f"6 * 7 = {result}")

Run the server first, then the client:

.. code-block:: bash

   # Terminal 1
   python rpc_server.py

   # Terminal 2
   python rpc_client.py
   # Output:
   #   6 * 7 = 42.0

**How it works:**

1. The client generates a unique ``correlation-id`` and creates a private response
   channel using its PID.
2. It publishes a request to ``rpc.math.multiply`` with ``response-topic`` and
   ``correlation-id`` headers.
3. The server processes the request, computes the result, and publishes it back to the
   client's ``response-topic``.
4. The client calls ``subscribe()`` with a timeout. The callback captures the response
   when the ``correlation-id`` matches.
5. If no response arrives before the timeout, a ``TimeoutError`` is raised.
