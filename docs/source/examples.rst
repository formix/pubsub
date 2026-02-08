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

Task Queue Pattern
-------------------

Implement a simple task queue with multiple workers:

.. code-block:: python

   # worker.py
   from pubsub import Channel, fetch
   import multiprocessing
   import json

   def worker(worker_id):
       channel = Channel(topic="tasks.queue")

       with channel:
           print(f"Worker {worker_id} started")

           while True:
               message = fetch(channel, timeout_seconds=5.0)
               if not message:
                   break

               task = json.loads(message.content.decode())
               print(f"Worker {worker_id} processing: {task['name']}")
               # Process task...
               time.sleep(task.get('duration', 1))
               print(f"Worker {worker_id} completed: {task['name']}")

   if __name__ == "__main__":
       # Start multiple workers
       workers = []
       for i in range(3):
           p = multiprocessing.Process(target=worker, args=(i,))
           p.start()
           workers.append(p)

       for w in workers:
           w.join()

.. code-block:: python

   # producer.py
   from pubsub import publish
   import json

   # Add tasks to the queue
   tasks = [
       {"name": "task1", "duration": 1},
       {"name": "task2", "duration": 2},
       {"name": "task3", "duration": 1},
   ]

   for task in tasks:
       publish("tasks.queue", json.dumps(task).encode())
       print(f"Queued: {task['name']}")

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

Request-Response Pattern
-------------------------

Request-response pattern using headers for routing. The server listens on a topic
with explicit action, and clients use headers to specify where responses should be sent.

.. code-block:: python

   # server.py
   from pubsub import Channel, subscribe, publish

   def rpc_server():
       # Server listens on topic with explicit action (no PID needed)
       request_channel = Channel(topic="rpc.multiply")

       with request_channel:
           def handle_request(request):
               # Extract routing info from headers
               response_topic = request.headers.get("response-topic")
               correlation_id = request.headers.get("correlation-id")

               if not response_topic or not correlation_id:
                   print("Invalid request: missing headers")
                   return

               # Process the request
               value = int(request.content.decode())
               result = value * 2

               # Send response back to client with correlation ID
               response_headers = {
                   "correlation-id": correlation_id
               }
               publish(response_topic, str(result).encode(), headers=response_headers)
               print(f"Processed request {correlation_id}: {value} * 2 = {result}")

           print("Server started on rpc.multiply")
           # Listens indefinitely; terminate process with SIGTERM/SIGINT for graceful shutdown
           subscribe(request_channel, handle_request)

   if __name__ == "__main__":
       rpc_server()

.. code-block:: python

   # client.py
   from pubsub import Channel, publish, fetch
   import os
   import uuid

   def call_multiply(value):
       # Generate unique correlation ID for this request
       correlation_id = str(uuid.uuid4())

       # Client creates its own response channel with PID
       client_pid = os.getpid()
       response_topic = f"rpc.client.{client_pid}"
       response_channel = Channel(topic=response_topic)

       with response_channel:
           # Send request with headers specifying response routing
           request_headers = {
               "response-topic": response_topic,
               "correlation-id": correlation_id
           }

           print(f"Client sending request with correlation-id: {correlation_id}")
           publish("rpc.multiply", str(value).encode(), headers=request_headers)

           # Wait for response
           response = fetch(response_channel)
           if response:
               response_correlation_id = response.headers.get("correlation-id")
               if response_correlation_id == correlation_id:
                   print(f"Received response for {response_correlation_id}")
                   return int(response.content.decode())
           return None

   if __name__ == "__main__":
       result = call_multiply(21)
       print(f"Result: {result}")  # 42
