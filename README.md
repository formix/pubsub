# PubSub

A lightweight, serverless publish-subscribe messaging system for Python (and other
languages) interprocess communications.

## Features

- **Interprocess communication** designed for true parallelism across separate processes
- **Topic-based routing** with wildcard support (`=` for single word, `+` for multiple words)
- **Multiple subscribers** can listen to the same topic independently
- **Message persistence** via file system until consumed
- **Non-blocking operations** using FIFO queues
- **Context manager support** for automatic resource cleanup
- **Thread-safe** operations as a bonus (though designed primarily for separate processes)

> **Design Philosophy:** This library is designed for **interprocess communication**. Each subscriber typically runs in its own process, enabling true parallel execution without GIL limitations. While thread-safe for convenience, the real power comes from process-based parallelism.

## Installation

```bash
pip install formix-pubsub
```

## API Reference

[https://pubsub.readthedocs.io](https://pubsub.readthedocs.io)

## Quick Start

### Basic Publish-Subscribe

```python
from pubsub import Channel, publish, subscribe

# Create a channel for a specific topic
# Note: Channels can subscribe using wildcards, but publish requires concrete topics
channel = Channel(topic="news.sports")

# Use context manager to ensure proper cleanup
with channel:
    # Publish to a concrete topic (no wildcards allowed when publishing)
    count = publish("news.sports", b"Team wins championship!")
    print(f"Published to {count} channel(s)")

    # Subscribe with a callback
    def handle_message(message):
        print(f"Received: {message.content.decode()}")

    subscribe(channel, handle_message, timeout_seconds=5.0)
```

### Fetching Messages Manually

```python
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
```

### Wildcard Topics

```python
from pubsub import Channel, publish, subscribe

# Channels can use wildcards to subscribe to multiple topics
# '=' matches a single word, '+' matches one or more words
channel = Channel(topic="news.=")  # Matches: news.sports, news.tech, news.world

with channel:
    # This channel will receive all matching messages
    def handle_message(msg):
        print(f"[{msg.topic}] {msg.content.decode()}")

    # Listens indefinitely until SIGTERM/SIGINT received
    subscribe(channel, handle_message)

# Elsewhere in your code, publish to concrete topics
# The wildcard channel above will receive these messages
publish("news.sports", b"Game results")
publish("news.tech", b"New release")
```

### Multiple Subscribers

> **Note:** This example uses threading for demonstration convenience. In production, subscribers typically run in **separate processes** for true parallelism without GIL limitations.

```python
import threading
from pubsub import Channel, publish, subscribe

topic = "broadcast"

# Create two independent channels for the same topic
channel1 = Channel(topic=topic)
channel2 = Channel(topic=topic)

with channel1, channel2:
    # Start two subscriber threads (in production, these would be separate processes)
    def subscriber1():
        # In production, use process.terminate() to signal shutdown
        subscribe(channel1, lambda msg: print(f"Sub1: {msg.content}"), timeout_seconds=2.0)

    def subscriber2():
        # Use timeout for demo; in production, terminate via signal
        subscribe(channel2, lambda msg: print(f"Sub2: {msg.content}"), timeout_seconds=2.0)

    thread1 = threading.Thread(target=subscriber1)
    thread2 = threading.Thread(target=subscriber2)
    thread1.start()
    thread2.start()

    # Publish - both subscribers receive the message
    publish(topic, b"Hello everyone!")

    thread1.join()
    thread2.join()
```

### Remote Procedure Call (RPC) Pattern

> **Note:** This example uses threading for demonstration. In production, the server and client would typically run in **separate processes** or even on different machines sharing a filesystem.

```python
import threading
import time
from pubsub import Channel, publish, subscribe, fetch

# Server: Process requests and send responses
def rpc_server():
    request_channel = Channel(topic="rpc.requests")

    with request_channel:
        def handle_request(request):
            print(f"Server received: {request.content.decode()}")

            # Extract response topic and correlation ID from headers
            response_topic = request.headers.get("response-topic")
            correlation_id = request.headers.get("correlation-id")

            if response_topic and correlation_id:
                # Process the request (simulate work)
                result = f"Processed: {request.content.decode()}"

                # Send response with correlation ID
                response_headers = {
                    "correlation-id": correlation_id
                }
                publish(response_topic, result.encode(), headers=response_headers)
                print(f"Server sent response with correlation-id: {correlation_id}")

        subscribe(request_channel, handle_request, timeout_seconds=5.0)

# Client: Send request and wait for response
def rpc_client():
    response_channel = Channel(topic="rpc.responses.client1")

    with response_channel:
        # Create request with response topic and correlation ID
        request_data = b"Calculate 2 + 2"
        request_headers = {
            "response-topic": "rpc.responses.client1",
            "correlation-id": str(int(time.time() * 1000000))  # Use timestamp as correlation ID
        }

        print(f"Client sending request with correlation-id: {request_headers['correlation-id']}")
        publish("rpc.requests", request_data, headers=request_headers)

        # Wait for response
        response = fetch(response_channel)
        if response:
            correlation_id = response.headers.get("correlation-id")
            print(f"Client received response with correlation-id: {correlation_id}")
            print(f"Result: {response.content.decode()}")

# Start server in background thread
server_thread = threading.Thread(target=rpc_server)
server_thread.start()

# Give server time to start
time.sleep(0.1)

# Execute client request
rpc_client()

# Wait for server to finish
server_thread.join()
```

## Configuration

### Environment Variables

#### PUBSUB_HOME

Override the default storage location for pubsub channels and messages.

**Default behavior:**
- Linux/Unix: `/dev/shm/pubsub` (tmpfs for best performance)
- Other systems: `<system_temp>/pubsub`

**Usage:**
```bash
# Set custom storage location
export PUBSUB_HOME=/tmp/my-pubsub

# Run your application
python your_app.py
```

**Example:**
```python
import os
os.environ['PUBSUB_HOME'] = '/path/to/custom/location'

from pubsub import Channel, publish, subscribe

# Now all channels will use the custom location
channel = Channel(topic="app.logs")
```

**Note:** The base directory is cached after first use, so `PUBSUB_HOME` should be set before importing or using pubsub functions.

## Architecture

### Interprocess Communication

This library uses filesystem-based IPC mechanisms, making it ideal for **process-level parallelism**:

- Each subscriber process runs independently with its own Python interpreter
- No shared memory between processes means no GIL contention
- True parallel execution across multiple CPU cores
- Publishers and subscribers can be completely separate applications

The thread-safe operations are a convenience feature, but the architecture shines when used across separate processes.

### Storage Location

Messages are stored in `/dev/shm/pubsub/` (tmpfs) by default for fast access. Each channel creates a directory containing:
- `queue`: FIFO pipe for message IDs
- `<message_id>`: Message content files

### Message Flow

1. **Publish**: Message are hard-linked to each matching channel directory, ID written to matching FIFOs
2. **Fetch/Subscribe**: Read ID from FIFO, load message from file, delete message file
3. **Cleanup**: Channel cleanup removes directory and all unconsumed messages

### Wildcards

- `=` matches a single word: `logs.=.error` matches `logs.app.error` but not `logs.error`
- `+` matches one or more words: `logs.+` matches `logs.error`, `logs.app.error`, `logs.app.module.error`

## Testing

Run the test suite:

```bash
# All tests
python -m unittest discover -s tests

# Specific test class
python -m unittest tests.test_pubsub.TestPublish -v

# Specific test
python -m unittest tests.test_channel.TestChannel.test_channel_creation -v
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- Commit message conventions (Conventional Commits)
- Development setup
- Running tests
- Pull request process

## Requirements

- Python 3.10+
- Linux/Unix with tmpfs support (`/dev/shm`)
- FIFO (named pipes) support

## License

See LICENSE file for details.
