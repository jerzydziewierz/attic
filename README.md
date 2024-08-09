# Attic: MQTT-based Data Logging System

Attic is a robust system designed to log sensor data from an MQTT broker to a SQLite database. It's built for efficiency, flexibility, and ease of use in local network environments.

## Key Features

* Efficient data handling: Processes 500 messages/sec using only ~0.5% CPU on modern desktops
* YAML-based configuration for easy setup and customization
* Python-based for easy extensibility and custom filtering
* Self-reporting performance metrics
* Multi-threaded support for multiple data streams, leveraging multi-core systems
* Automatic log file rotation for easy data management and transport
* SQLite database storage, compatible with popular data analysis tools like pandas

## Getting Started

Attic is designed to run as a service, either on the same node as the MQTT broker or on an adjacent node.

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/your-repo/attic.git
   cd attic
   ```

2. Set up the environment:
   ```
   ./scripts/setup-dev.sh
   ```

3. Install the package:
   ```
   pip install -e .
   ```

### Configuration

Edit the `config/config.yaml` file to set up your MQTT broker details and data streams.

### Running Attic

Run Attic using:

```
python run_attic.py
```

For production use, set it up as a system service using the provided `src/attic.service` file.

## Key Concepts

### Streams

A "stream" in Attic is a single thread that listens to a specific MQTT topic and saves events to its configured database. Streams can listen to wildcard topics (e.g., `#` or `+/+/+/+`) to capture multiple event types.

### Log File Rotation

Attic manages data growth through automatic log file rotation:

* Each stream's output is placed in a dedicated folder
* Files are named by their creation timestamp
* New files are started at configurable intervals
* A new folder is created daily to prevent clutter

### Timestamp Handling

Attic uses Unix epoch time in microseconds (seconds * 1e6) for high-resolution event timing. Note that the "reception_timestamp" is the local time of the log saver, not the event source.

## Performance Monitoring

Attic includes a performance monitoring UI built with Gradio. Run it using:

```
python tools/attic_performance_ui.py
```

This provides real-time insights into message rates, stream utilization, and system status.

## Future Work

* Optimize log file rotation for minimal performance impact
* Add support for Avro packets from MQTT broker for space efficiency
* Explore porting to async Rust for potential performance gains

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


