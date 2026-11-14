# formix-pubsub

[![PyPI version](https://img.shields.io/pypi/v/formix-pubsub)](https://pypi.org/project/formix-pubsub/)
[![Python](https://img.shields.io/pypi/pyversions/formix-pubsub)](https://pypi.org/project/formix-pubsub/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A serverless, zero-dependency publish-subscribe library for Python interprocess communication.

## Why Serverless?

Unlike traditional pub/sub systems (Redis, RabbitMQ, ZeroMQ), **formix-pubsub requires no broker, no server process, and no external service**. Messages are stored as files in a per-subscriber directory (on the shared-memory filesystem, `/dev/shm`, on Linux) and subscribers are woken up by the operating system's file-change notifications, making communication fast and entirely local. It runs on **Linux, macOS and Windows**.

- **No infrastructure** — install and use, nothing to start or configure
- **Zero dependencies** — pure Python, standard library only
- **Automatic cleanup** — channels are tied to process IDs; stale channels from crashed processes are detected and cleaned up automatically
- **Messages persist until consumed** — published messages are stored as files and delivered to all matching subscribers

## Installation

```bash
pip install formix-pubsub
```

Requires Python 3.11 or later.

## Quick Start: Publish & Subscribe Across Processes

The core use case is communication between separate processes. Create two files:

**subscriber.py**

```python
from pubsub import Channel, subscribe

channel = Channel(topic="greetings")

with channel:
    def on_message(msg):
        print(f"Received: {msg.content.decode()}")

    # Blocks and listens until terminated with Ctrl+C (SIGINT), or SIGTERM on Linux and macOS
    subscribe(channel, on_message)
```

**publisher.py**

```python
from pubsub import publish

count = publish("greetings", b"Hello from another process!")
print(f"Published to {count} subscriber(s)")
```

Run the subscriber first, then the publisher in a second terminal:

```bash
# Terminal 1
python subscriber.py

# Terminal 2
python publisher.py
```

The subscriber prints `Received: Hello from another process!` and keeps listening. Press `Ctrl+C` to stop it gracefully.

## Non-Blocking Fetch

Use `fetch()` to poll for messages without blocking. It returns `None` immediately when the queue is empty.

```python
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
```

This is useful when your application needs to check for messages as part of a larger loop without surrendering control flow to `subscribe()`.

## RPC Pattern (Request-Response)

For request-response workflows, use message headers to route replies back to the caller. This example implements a multiply service.

**rpc_server.py**

```python
from pubsub import Channel, subscribe, publish

channel = Channel(topic="rpc.math.multiply")

with channel:
    def handle_request(request):
        response_topic = request.headers.get("response-topic")
        correlation_id = request.headers.get("correlation-id")

        if not response_topic or not correlation_id:
            print(f"Malformed request (missing headers), skipping.")
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
```

**rpc_client.py**

```python
import os
import uuid

from pubsub import Channel, publish, subscribe

def rpc_multiply(a: float, b: float, timeout: float = 2.0) -> float:
    """Send a multiply request and wait for the response."""

    correlation_id = str(uuid.uuid4())
    result = {correlation_id: None}

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
            response_correlation_id = msg.headers.get("correlation-id")
            result[response_correlation_id] = float(msg.content.decode())

        subscribe(response_channel, on_response, timeout_seconds=timeout)

    if result[correlation_id] is None:
        raise TimeoutError(
            f"No response received for correlation-id {correlation_id} "
            f"within {timeout}s"
        )

    return result[correlation_id]


if __name__ == "__main__":
    result = rpc_multiply(6, 7)
    print(f"6 * 7 = {result}")
```

Run the server first, then the client:

```bash
# Terminal 1
python rpc_server.py

# Terminal 2
python rpc_client.py
# Output:
#   6 * 7 = 42.0
```

**How it works:**

1. The client generates a unique `correlation-id` and creates a private response channel using its PID.
2. It publishes a request to `rpc.math.multiply` with `response-topic` and `correlation-id` headers.
3. The server processes the request, computes the result, and publishes it back to the client's `response-topic`.
4. The client calls `subscribe()` with a timeout. The callback captures the response when the `correlation-id` matches.
5. If no response arrives before the timeout, a `TimeoutError` is raised.

## Wildcard Topics

Wildcards let a single channel receive messages from multiple topics:

| Wildcard | Matches | Example |
|----------|---------|---------|
| `=` | Exactly one word | `logs.=` matches `logs.info`, `logs.error` but not `logs.app.info` |
| `+` | One or more words | `logs.+` matches `logs.info`, `logs.error`, and `logs.app.info` |

```python
from pubsub import Channel, subscribe, publish

# Subscribe to all log topics
channel = Channel(topic="logs.+")

with channel:
    def on_log(msg):
        print(f"[{msg.topic}] {msg.content.decode()}")

    # In another process:
    # publish("logs.info", b"Started")
    # publish("logs.app.debug", b"Cache hit")

    subscribe(channel, on_log)
```

> **Note:** Wildcards are only valid when creating channels for subscribing. You must publish to concrete topics (e.g. `logs.info`, not `logs.+`).

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `PUBSUB_HOME` | Directory for channel and message storage | `/dev/shm/pubsub` on Linux, `<system temp dir>/pubsub` elsewhere |
| `PUBSUB_WATCHER` | Set to `poll` to wait for messages by polling instead of using the operating system's file-change notifications | notifications, with polling as automatic fallback |

## Platform Support

| | Linux | macOS | Windows |
|---|---|---|---|
| Storage | `/dev/shm/pubsub` | `<temp>/pubsub` | `%TEMP%\pubsub` |
| Wake-up on new message | inotify | kqueue | `FindFirstChangeNotification` |
| Stopping a subscriber | `SIGINT`, `SIGTERM` | `SIGINT`, `SIGTERM` | Ctrl+C (`SIGINT`), Ctrl+Break (`SIGBREAK`) |

Notes:

- **Everything lives in one directory.** Publishers and subscribers must use the same `PUBSUB_HOME`. By default that directory belongs to the current user, so set `PUBSUB_HOME` to a shared directory to let several users exchange messages.
- **Windows:** the storage directory should be on NTFS. On file systems without hard links (FAT, exFAT, some network shares) messages are copied instead, which is slower. `SIGTERM` is never delivered on Windows: a process killed with `Stop-Process` or `taskkill` is stopped immediately, without the graceful shutdown. Use Ctrl+C or Ctrl+Break, or run `subscribe` with a timeout.
- **Windows path length:** without long path support, Windows limits paths to 259 characters. If a topic is too long for that, `Channel(...)` raises an `OSError` that explains how to lift the limit (re-run the Python installer and tick *Disable path length limit*, or set the `LongPathsEnabled` registry value to `1`).
- **Network and WSL file systems** (`/mnt/c` in WSL, NFS, SMB) do not reliably report changes. pubsub still works there, but notices new messages after at most 100 ms instead of immediately.

## API Summary

### `publish(topic, data, headers=None) -> int`

Publish a message to all channels matching `topic`. Returns the number of channels that received the message.

### `fetch(channel, auto_ack=True) -> Message | None`

Fetch the next message from a channel without blocking. Returns `None` if the channel is empty. Raises `RuntimeError` if a `subscribe` is listening on the channel.

By default the message is deleted from the channel as soon as it is fetched. With `auto_ack=False` the message stays locked in the channel until you dispose of it with `ack` or `nack`.

### `ack(channel, message)` and `nack(channel, message, poison=False)`

For messages fetched with `auto_ack=False`: `ack` deletes the message, `nack` gives it back to the channel under its own id, so a later `fetch` or `subscribe` delivers it again (after the messages already listed, in id order). Calling them twice, or after the channel is closed, does nothing. A message that is neither acknowledged nor rejected stays locked until the channel is closed. A message that is rejected over and over is delivered over and over.

To stop a message that would fail every time, reject it with `nack(channel, message, poison=True)`: it is moved to the `poison` folder of the channel (`channel.poison_path`) under its own name and this channel never delivers it again, so that whatever handles failures can deal with it (read a file with `Message.read`). Every `nack` is logged: at `INFO` level when the message goes back to the channel, at `WARNING` level when it is moved as poison. The poison folder is deleted with the channel when it is closed, so handle the poison messages before that.

```python
message = fetch(channel, auto_ack=False)
if message is not None:
    try:
        handle(message)
        ack(channel, message)
    except TemporaryError:
        nack(channel, message)  # try again later
    except PermanentError:
        nack(channel, message, poison=True)  # never retry this one
```

### `subscribe(channel, callback, timeout_seconds=0, auto_ack=True) -> int`

Block and deliver messages to `callback` as they arrive. Set `timeout_seconds` to limit listening duration (0 = indefinite). Returns the number of messages processed, or -1 if interrupted by a signal. A channel has a single consumer: calling `subscribe` on a channel that is already being listened to raises `RuntimeError`, and so does calling `fetch` on it (including from the callback). With `auto_ack=False`, the callback must call `ack` or `nack` itself; a message it leaves alone, or whose callback raises, stays locked in the channel.

### `Channel(topic)`

Represents a subscription endpoint. Its directory is created by `open()` (or by entering the `with` block) and deleted, with any unread message, by `close()`. Messages published before the channel is open are not delivered to it. Topics may include `=` and `+` wildcards for pattern matching.

### `Channel.cleanup_inactive()`

Deletes what crashed processes left behind: channels of processes that are no longer running, interrupted deletions, and temporary message files older than one hour. It runs only when you call it.

### `Message`

A received message with the following attributes:

- `id` — unique message identifier (64 bits; the upper bits are the creation time in milliseconds)
- `timestamp` — microsecond-precision timestamp
- `topic` — the concrete topic the message was published to
- `content` — payload as `bytes`
- `headers` — optional `dict[str, str | int | float | bool | None]`

## Best Practices

1. **Use separate processes** — designed for true parallelism without GIL limitations
2. **Always use context managers** — `with Channel(...) as ch:` ensures the channel directory is cleaned up
3. **Publish to concrete topics** — wildcards are for subscribing only
4. **Structure topic hierarchies** — e.g. `app.service.event` for flexible wildcard matching
5. **Stop subscribers with signals** — `SIGTERM` or `SIGINT` (Ctrl+C or Ctrl+Break on Windows) triggers graceful shutdown
6. **Don't rely on order between publishers** — messages from one publisher arrive in the order they were published, but messages published concurrently by several publishers may be delivered in any order

## License

[MIT](LICENSE)
