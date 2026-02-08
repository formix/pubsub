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
           subscribe(channel, handle_user_event, timeout_seconds=60.0)

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
           subscribe(channel, handle_user_event, timeout_seconds=60.0)

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

   # Cleanup
   email_proc.terminate()
   analytics_proc.terminate()

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
               subscribe(channel, handle_log, timeout_seconds=300.0)

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

Simple request-response using two channels:

.. code-block:: python

   # server.py
   from pubsub import Channel, subscribe, publish
   import json

   def server():
       request_channel = Channel(topic="requests")

       with request_channel:
           def handle_request(msg):
               request = json.loads(msg.content.decode())
               request_id = request['id']

               # Process request
               result = {"id": request_id, "result": request['value'] * 2}

               # Send response
               response_topic = f"responses.{request_id}"
               publish(response_topic, json.dumps(result).encode())
               print(f"Processed request {request_id}")

           print("Server started")
           subscribe(request_channel, handle_request, timeout_seconds=60.0)

   if __name__ == "__main__":
       server()

.. code-block:: python

   # client.py
   from pubsub import Channel, publish, fetch
   import json
   import uuid

   def send_request(value):
       request_id = str(uuid.uuid4())
       response_channel = Channel(topic=f"responses.{request_id}")

       with response_channel:
           # Send request
           request = {"id": request_id, "value": value}
           publish("requests", json.dumps(request).encode())

           # Wait for response
           response_msg = fetch(response_channel, timeout_seconds=5.0)
           if response_msg:
               response = json.loads(response_msg.content.decode())
               return response['result']
           return None

   if __name__ == "__main__":
       result = send_request(21)
       print(f"Result: {result}")  # 42
