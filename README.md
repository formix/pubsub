# PubSub

A Python publish-subscribe messaging library for building event-driven applications.

## Features

- Simple and intuitive API
- Type-safe message handling
- Flexible topic-based routing
- Synchronous and asynchronous support
- Lightweight and performant

## Installation

```bash
pip install pubsub
```

## Quick Start

```python
from pubsub import Publisher, Subscriber

# Create publisher and subscriber
publisher = Publisher()
subscriber = Subscriber()

# Define a message handler
def handle_message(topic: str, message: dict):
    print(f"Received on {topic}: {message}")

# Subscribe to a topic
subscriber.subscribe("user.created", handle_message)

# Publish a message
publisher.publish("user.created", {"user_id": 123, "username": "john_doe"})
```

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/yourusername/pubsub.git
cd pubsub

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black src/ tests/
```

### Type Checking

```bash
mypy src/
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.