# PubSub

A lightweight, serverless publish-subscribe messaging system for Python (and other
languages) interprocess communications.

## Features

- **Topic-based routing** with wildcard support (`=` for single word, `+` for multiple words)
- **Multiple subscribers** can listen to the same topic independently
- **Message persistence** via file system until consumed
- **Non-blocking operations** using FIFO queues
- **Context manager support** for automatic resource cleanup
- **Thread-safe** message publishing and consumption

## Installation

```bash
pip install formix-pubsub
```

## Quick Start

### Basic Publish-Subscribe

```python
from pubsub import Channel, publish, subscribe

# Create a channel for a topic
channel = Channel(topic="news.sports")

# Use context manager to ensure proper cleanup
with channel:
    # Publish a message
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
from pubsub import Channel, subscribe

# Single word wildcard (=) - matches one word
channel = Channel(topic="news.=")  # Matches: news.sports, news.tech, news.world

# Multiple word wildcard (+) - matches one or more words
channel = Channel(topic="logs.+")  # Matches: logs.error, logs.app.debug, logs.system.critical

with channel:
    # This channel will receive all matching messages
    def handle_message(msg):
        print(f"[{msg.topic}] {msg.content.decode()}")
    
    subscribe(channel, handle_message, timeout_seconds=10.0)
```

### Multiple Subscribers

```python
import threading
from pubsub import Channel, publish, subscribe

topic = "broadcast"

# Create two independent channels for the same topic
channel1 = Channel(topic=topic)
channel2 = Channel(topic=topic)

with channel1, channel2:
    # Start two subscriber threads
    def subscriber1():
        subscribe(channel1, lambda msg: print(f"Sub1: {msg.content}"), timeout_seconds=5.0)
    
    def subscriber2():
        subscribe(channel2, lambda msg: print(f"Sub2: {msg.content}"), timeout_seconds=5.0)
    
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

## API Reference

### Channel

Represents a topic subscription point with a dedicated FIFO queue.

```python
Channel(topic: str)
```

**Parameters:**
- `topic` (str): Topic string with dots separating terms. Supports wildcards `=` (single word) and `+` (multiple words). Valid characters: `[a-zA-Z0-9+=.-]`

**Methods:**
- `open()`: Opens the FIFO queue for reading (called automatically by context manager)
- `close()`: Closes the queue and cleans up resources
- `__enter__()`, `__exit__()`: Context manager support

**Usage:**
```python
channel = Channel(topic="app.logs")
with channel:
    # Channel is open and ready
    pass
# Channel is automatically closed
```

### publish()

Publishes a message to all matching channels.

```python
publish(topic: str, data: bytes, headers: dict = None) -> int
```

**Parameters:**
- `topic` (str): Topic to publish to (only alphanumeric characters, dots, and hyphens allowed: `[a-zA-Z0-9.-]`)
- `data` (bytes): Message payload
- `headers` (dict): Optional dictionary of string key-value pairs for metadata

**Returns:**
- `int`: Number of channels the message was published to

**Raises:**
- `ValueError`: If topic contains invalid characters (only `[a-zA-Z0-9.-]` allowed)

**Example with headers:**
```python
from pubsub import publish

# Publish with custom headers
headers = {
    "priority": "high",
    "correlation-id": "12345"
}
publish("app.events", b"Event data", headers=headers)
```

### fetch()

Fetches a single message from a channel (non-blocking).

```python
fetch(channel: Channel) -> Optional[Message]
```

**Parameters:**
- `channel` (Channel): Open channel to fetch from

**Returns:**
- `Message`: Message object if available, `None` if queue is empty

**Note:** The channel must be opened (use `with channel:`) before calling `fetch()`.

### subscribe()

Subscribes to a channel and processes messages with a callback.

```python
subscribe(channel: Channel, callback: Callable[[Message], None], timeout_seconds: float = 0) -> int
```

**Parameters:**
- `channel` (Channel): Open channel to subscribe to
- `callback` (Callable): Function called for each message received
- `timeout_seconds` (float): How long to listen (0 = indefinite)

**Returns:**
- `int`: Number of messages processed

**Raises:**
- `ValueError`: If timeout is negative

**Note:** The channel must be opened (use `with channel:`) before calling `subscribe()`.

### Message

Represents a pub/sub message.

**Attributes:**
- `id` (int): Unique message identifier (timestamp-based with random bits)
- `timestamp` (int): Message creation timestamp in microseconds
- `topic` (str): Message topic
- `content` (bytes): Message payload
- `content_length` (int): Length of content in bytes
- `headers` (dict): Dictionary of string key-value pairs containing message metadata

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

### Storage Location

Messages are stored in `/dev/shm/pubsub/` (tmpfs) by default for fast access. Each channel creates a directory containing:
- `queue`: FIFO pipe for message IDs
- `<message_id>`: Message content files

### Message Flow

1. **Publish**: Message written to tmp, then hard-linked to each matching channel directory, ID written to FIFO
2. **Fetch/Subscribe**: Read ID from FIFO, load message from file, delete message file
3. **Cleanup**: Channel cleanup removes directory and all unconsumed messages

### Wildcards

- `=` matches a single word: `logs.=.error` matches `logs.app.error` but not `logs.error`
- `+` matches one or more words: `logs.+` matches `logs.error`, `logs.app.error`, `logs.app.module.error`

Wildcards are converted to regex patterns for matching.

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

## Requirements

- Python 3.12+
- Linux/Unix with tmpfs support (`/dev/shm`)
- FIFO (named pipes) support

## License

See LICENSE file for details.
