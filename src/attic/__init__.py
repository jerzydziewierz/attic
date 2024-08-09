import argparse
import yaml
import os
import signal
import sqlite3
import threading
import time
import datetime
import pytz
import typing
from typing import Callable, Any, List, Dict
import pathlib
import json
from paho.mqtt import client as mqtt
from .safetimestring import datetime_to_safestring, safestring_to_datetime, timefolders

stdout = print

class SharedState:
    def __init__(self):
        self.totalMessageCount: int = 0
        self.streams: List[Dict] = []
        self.configs: List[Dict] = []
        self.clients: List[mqtt.Client] = []

    def add_stream(self, stream: Dict):
        self.streams.append(stream)

    def add_config(self, config: Dict):
        self.configs.append(config)

    def add_client(self, client: mqtt.Client):
        self.clients.append(client)

def initialize_stream_state(shared_state: SharedState, q_stream_idx: int, intended_topic: str) -> None:
    """
    Initialize the state for a specific stream in the shared state.

    Args:
        shared_state (SharedState): The shared state object.
        q_stream_idx (int): The index of the stream.
        intended_topic (str): The intended MQTT topic for the stream.
    """
    debug_mode = True
    if debug_mode:
        stdout(f'{len(shared_state.streams)=} {q_stream_idx=}')
    shared_state.streams[q_stream_idx] = {
        "messageCount": 0,
        "intendedTopic": intended_topic,
        "lastMessage": None,
        "sqlite_cursor": None,
        "sqlite_connection": None,
        "next_rotation_time": 0,
        "stop_request": False,
        "stop_request_ack": False,
        "process_start_time": 0.0,
        "process_end_time": time.time(),
        "previous_end_time": 0.0,
        "totalIdleTime": 0.0,
        "totalProcessingTime": 0.0,
    }

def renew_database_link(q_stream_path: str, q_stream_idx: int, shared_state: SharedState, log_rotation_time: int) -> typing.Tuple[sqlite3.Cursor, sqlite3.Connection]:
    """
    Create a new database connection and cursor.

    Args:
        q_stream_path (str): The path to store the database file.
        q_stream_idx (int): The index of the stream.
        shared_state (SharedState): The shared state object.
        log_rotation_time (int): The time interval for log rotation.

    Returns:
        tuple: A tuple containing the SQLite cursor and connection objects.
    """
    pathlib.Path(q_stream_path).mkdir(parents=True, exist_ok=True)
    safedatestring = datetime_to_safestring(datetime.datetime.now(tz=pytz.UTC))
    file_name = f'{safedatestring}.sqlite'
    full_folder_name = timefolders(q_stream_path, datetime.datetime.now(tz=pytz.UTC))
    full_folder_name.mkdir(parents=True, exist_ok=True)
    sqlite_db_path = full_folder_name.joinpath(file_name)
    stdout(f'{q_stream_idx=} | topic={shared_state.configs[q_stream_idx]["prefix"]} |  creating new file {sqlite_db_path}')
    sqlite_connection_r = sqlite3.connect(sqlite_db_path)
    sqlite_cursor_r = sqlite_connection_r.cursor()
    sqlite_cursor_r.execute('CREATE TABLE IF NOT EXISTS data (reception_timestamp INTEGER, topic TEXT, payload BLOB)')
    sqlite_cursor_r.execute('CREATE INDEX IF NOT EXISTS topics ON data (topic)')
    sqlite_connection_r.commit()
    shared_state.streams[q_stream_idx]['sqlite_cursor'] = sqlite_cursor_r
    shared_state.streams[q_stream_idx]['sqlite_connection'] = sqlite_connection_r
    shared_state.streams[q_stream_idx]['next_rotation_time'] = time.time() + log_rotation_time
    return sqlite_cursor_r, sqlite_connection_r

def handle_database_operations(shared_state: SharedState, q_stream_idx: int, msg, log_rotation_time: int, q_stream_path: str) -> None:
    """
    Handle database operations for incoming messages.

    Args:
        shared_state (SharedState): The shared state object.
        q_stream_idx (int): The index of the stream.
        msg: The incoming MQTT message.
        log_rotation_time (int): The time interval for log rotation.
        q_stream_path (str): The path to store the database file.
    """
    stream_state = shared_state.streams[q_stream_idx]
    
    if stream_state['sqlite_cursor'] is None:
        if not stream_state['stop_request']:
            sqlite_cursor, sqlite_connection = renew_database_link(q_stream_path, q_stream_idx, shared_state, log_rotation_time)
        else:
            stream_state['stop_request_ack'] = True
            return
    else:
        sqlite_cursor = stream_state['sqlite_cursor']
        sqlite_connection = stream_state['sqlite_connection']

        if stream_state['stop_request']:
            sqlite_connection.commit()
            sqlite_cursor.close()
            sqlite_connection.close()
            stream_state['sqlite_cursor'] = None
            stream_state['sqlite_connection'] = None
            stream_state['stop_request_ack'] = True
            return

        if time.time() > stream_state['next_rotation_time']:
            print(f'{q_stream_idx=} rotating log...')
            sqlite_connection.commit()
            sqlite_cursor.close()
            sqlite_connection.close()
            stream_state['sqlite_cursor'] = None
            stream_state['sqlite_connection'] = None
            sqlite_cursor, sqlite_connection = renew_database_link(q_stream_path, q_stream_idx, shared_state, log_rotation_time)

    topic = msg.topic
    payload = msg.payload
    timestamp_unix = int(1e6 * time.time())
    timestamp_iso_string = datetime.datetime.now(tz=pytz.UTC).isoformat(timespec='microseconds')
    stream_state['lastRxTimestamp_unix'] = timestamp_unix
    stream_state['lastRxTimestamp_iso_string'] = timestamp_iso_string

    if sqlite_cursor is not None:
        sqlite_cursor.execute("INSERT INTO data VALUES (?, ?, ?)", (timestamp_unix, topic, payload))
        shared_state.totalMessageCount += 1
        stream_state['messageCount'] += 1
        stream_state['process_end_time'] = time.time()
        q_idle_time = stream_state['process_start_time'] - stream_state['previous_end_time']
        q_processing_time = stream_state['process_end_time'] - stream_state['process_start_time']
        stream_state['totalIdleTime'] += q_idle_time
        stream_state['totalProcessingTime'] += q_processing_time
    else:
        print(f'{q_stream_idx=} sqlite_cursor is None, ignoring message. This is probably a bug.')

def make_on_message_callback(
        shared_state: SharedState,
        q_stream_idx: int,
        intended_topic: str,
        q_stream_path: str = "",
        log_rotation_time: int = 600):
    """
    Create an on_message callback function for MQTT client.

    Args:
        shared_state (SharedState): The shared state object.
        q_stream_idx (int): The index of the stream.
        intended_topic (str): The intended MQTT topic for the stream.
        q_stream_path (str): The path to store the database file.
        log_rotation_time (int): The time interval for log rotation.

    Returns:
        function: The on_message callback function.
    """
    initialize_stream_state(shared_state, q_stream_idx, intended_topic)

    def curried_on_message(_1, _2, msg):
        stream_state = shared_state.streams[q_stream_idx]
        stream_state['process_previous_start_time'] = stream_state['process_start_time']
        stream_state['process_start_time'] = time.time()
        stream_state['previous_end_time'] = stream_state['process_end_time']

        try:
            handle_database_operations(shared_state, q_stream_idx, msg, log_rotation_time, q_stream_path)
        except Exception as ex:
            print(f'error in on_message: {ex}')
            import traceback
            print(traceback.format_exc())
            print(f'message lost, not retrying.')

    return curried_on_message

def make_on_connect(topics):
    """
    Create an on_connect callback function for MQTT client.

    Args:
        topics (list): List of topics to subscribe to.

    Returns:
        function: The on_connect callback function.
    """
    def curried_on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 5:
            stdout('mqtt broker rejected connection. This is probably because the username and password are incorrect.')
            stdout('continue...')
        else:
            stdout(f'connected to mqtt broker with result code {reason_code} and flags {flags} |', end='')
            for topic in topics:
                client.subscribe(topic)
                stdout(f'| subscribed to {topic} |', end='')
            stdout()

    return curried_on_connect

def on_disconnect(client, userdata, flags, reason_code, properties):
    """
    Callback function for MQTT client disconnection.

    Args:
        client: The MQTT client instance.
        userdata: The private user data as set in Client() or user_data_set().
        flags: Response flags sent by the broker.
        reason_code: The disconnection result.
        properties: The MQTT v5.0 properties.
    """
    stdout(f'disconnected from mqtt broker with reason code {reason_code} and flags {flags}')

def signal_handler(shared_state: SharedState):
    """
    Create a signal handler for graceful shutdown.

    Args:
        shared_state (SharedState): The shared state object.

    Returns:
        function: The signal handler function.
    """
    def handler(sig, frame):
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        stdout('Abort signal received! Attempting a graceful stop, hold on ...')
        for stream_idx2 in range(len(shared_state.streams)):
            try:
                stdout(f'sending stop signal to {stream_idx2=}...')
                shared_state.streams[stream_idx2]['stop_request'] = True
                while not shared_state.streams[stream_idx2]['stop_request_ack']:
                    time.sleep(0.2)
                    stdout('.', end='', flush=True)
            except Exception as ex1:
                stdout(f'error {ex1} when stopping sqlite on {stream_idx2=}, not retrying.')

        for client in shared_state.clients:
            try:
                stdout(f'stopping client {client} ...')
                client.loop_stop()
                client.disconnect()
            except Exception as ex2:
                stdout(f'error {ex2} when stopping client {client}, not retrying.')

        from sys import exit
        exit(0)
    
    return handler

def parse_arguments():
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default='config/config.yaml',
                        help='fully qualified path to the configuration file, yaml format')
    return parser.parse_args()

def load_configuration(config_path):
    """
    Load configuration from a YAML file.

    Args:
        config_path (str): Path to the configuration file.

    Returns:
        dict: Loaded configuration.
    """
    try:
        with open(config_path, 'r') as stream:
            return yaml.safe_load(stream)
    except FileNotFoundError as no_config_file:
        stdout(f'error: {no_config_file}')
        exit(1)
    except yaml.YAMLError as exc:
        stdout(exc)
        exit(1)

def prepare_output_folders(config, data_path):
    """
    Prepare output folders for each stream.

    Args:
        config (dict): The configuration dictionary.
        data_path (str): The base data path.
    """
    stream_count = len(config['streams'])
    for stream in range(stream_count):
        folder_prefix = config['streams'][stream]['prefix'] or str(stream)
        folder_suffix = config['streams'][stream]['suffix']
        folder_name = folder_prefix + folder_suffix
        stream_path = os.path.join(data_path, folder_name)
        stdout(f'creating {stream_path}')
        os.makedirs(stream_path, exist_ok=True)

def setup_mqtt_clients(config, shared_state, data_path):
    """
    Set up MQTT clients for each stream.

    Args:
        config (dict): The configuration dictionary.
        shared_state (SharedState): The shared state object.
        data_path (str): The base data path.
    """
    for stream_idx, stream_config in enumerate(config['streams']):
        shared_state.add_config(stream_config)

        folder_prefix = stream_config['prefix']
        if not folder_prefix:
            raise ValueError('folder prefix cannot be empty.')
        folder_suffix = stream_config['suffix']
        folder_name = folder_prefix + folder_suffix
        stream_path = os.path.join(data_path, folder_name)

        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        shared_state.add_client(mqtt_client)
        shared_state.add_stream(dict())

        on_connect = make_on_connect([stream_config['topic']])
        mqtt_client.on_connect = on_connect
        mqtt_client.on_disconnect = on_disconnect

        this_on_message = make_on_message_callback(
            shared_state,
            stream_idx,
            intended_topic=stream_config['topic'],
            q_stream_path=stream_path,
            log_rotation_time=stream_config['file-rotation-time-seconds']
        )
        mqtt_client.on_message = this_on_message
        if stream_config['user']:
            mqtt_client.username_pw_set(stream_config['user'], stream_config['password'])
        mqtt_client.connect(stream_config['mqtt-broker-address'], stream_config['mqtt-broker-port'], 10)
        mqtt_client.loop_start()

def setup_performance_logging(config):
    """
    Set up performance logging if enabled in the configuration.

    Args:
        config (dict): The configuration dictionary.

    Returns:
        tuple: Performance client and topic, or (None, None) if logging is disabled.
    """
    if config['log-performance']:
        performance_topic = config['log-performance-stream']['topic']
        performance_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if config['log-performance-stream']['user']:
            performance_client.username_pw_set(config['log-performance-stream']['user'],
                                               config['log-performance-stream']['password'])
        performance_client.connect(config['log-performance-stream']['mqtt-broker-address'],
                                   config['log-performance-stream']['mqtt-broker-port'], 60)
        performance_client.loop_start()
        return performance_client, performance_topic
    return None, None

def calculate_performance_metrics(shared_state, start_time, last_message_count, feedback_period):
    """
    Calculate performance metrics for the current iteration.

    Args:
        shared_state (SharedState): The shared state object.
        start_time (float): The start time of the application.
        last_message_count (int): The message count from the previous iteration.
        feedback_period (int): The time period between performance updates.

    Returns:
        tuple: A tuple containing various performance metrics.
    """
    current_time = time.time()
    elapsed_time = current_time - start_time
    total_message_count = shared_state.totalMessageCount
    messages_per_second_total = total_message_count / elapsed_time
    messages_per_second_recent = (total_message_count - last_message_count) / feedback_period
    elapsed_time_hours = elapsed_time / 3600
    return (current_time, elapsed_time, total_message_count, messages_per_second_total,
            messages_per_second_recent, elapsed_time_hours)

def process_stream_performance(shared_state, stream_idx, config):
    """
    Process performance metrics for a single stream.

    Args:
        shared_state (SharedState): The shared state object.
        stream_idx (int): The index of the stream.
        config (dict): The configuration dictionary.

    Returns:
        dict: A dictionary containing performance details for the stream.
    """
    stream_state = shared_state.streams[stream_idx]
    idle_time = stream_state['totalIdleTime']
    processing_time = stream_state['totalProcessingTime']
    total_time = idle_time + processing_time
    if total_time > 0:
        idle_time_ratio = idle_time / total_time
        utilisation_ratio = 100 * (1.0 - idle_time_ratio)
        stream_connected = shared_state.clients[stream_idx].is_connected()
        if not stream_connected:
            stdout(f"stream {stream_idx} is not connected, attempting to reconnect ...")
            try:
                reconnect_mqtt_client(shared_state, stream_idx, config)
            except Exception as ex:
                stdout(f"error {ex} when reconnecting stream {stream_idx}, not retrying.")

        return {
            'stream_prefix': config['streams'][stream_idx]['prefix'],
            'stream_idx': stream_idx,
            'utilisation_ratio': utilisation_ratio,
            'messages_this_channel': stream_state['messageCount'],
            'last_rx_timestamp_unix': stream_state['lastRxTimestamp_unix'],
            'last_rx_timestamp_iso': stream_state['lastRxTimestamp_iso_string'],
            'is_connected': stream_connected,
        }
    return None

def reconnect_mqtt_client(shared_state, stream_idx, config):
    """
    Attempt to reconnect a disconnected MQTT client.

    Args:
        shared_state (SharedState): The shared state object.
        stream_idx (int): The index of the stream.
        config (dict): The configuration dictionary.
    """
    h_client = shared_state.clients[stream_idx]
    stream_config = config['streams'][stream_idx]
    h_client.loop_stop()
    time.sleep(0.1)
    h_client.disconnect()
    time.sleep(0.1)
    if stream_config['user']:
        h_client.username_pw_set(username=stream_config['user'], password=stream_config['password'])
    time.sleep(0.1)
    on_connect = make_on_connect([stream_config['topic']])
    h_client.on_connect = on_connect
    h_client.connect(host=stream_config['mqtt-broker-address'],
                     port=stream_config['mqtt-broker-port'],
                     keepalive=10)
    time.sleep(0.1)
    h_client.loop_start()
    time.sleep(0.1)

def publish_performance_message(performance_client, performance_topic, performance_message):
    """
    Publish performance message to MQTT broker.

    Args:
        performance_client (mqtt.Client): The MQTT client for performance logging.
        performance_topic (str): The topic to publish performance messages to.
        performance_message (dict): The performance message to publish.
    """
    if performance_client is not None:
        performance_client.publish(
            topic=performance_topic,
            payload=json.dumps(performance_message)
        )

def run():
    """
    Main function to run the Attic application.
    """
    stdout("starting attic, version 0.0.1")

    args = parse_arguments()
    if args.config is None:
        stdout('no config file specified. cannot continue.')
        exit(1)

    shared_state = SharedState()
    config_path = os.path.abspath(args.config)
    stdout(f'using configuration from: {config_path}')
    config = load_configuration(config_path)

    stream_count = len(config['streams'])
    stdout(f'got {stream_count} streams')
    for stream in range(stream_count):
        stdout(f'stream {stream}:')
        for key, value in config["streams"][stream].items():
            if key == 'password':
                stdout(f'{key:>30} -> {"*" * len(value)}')
            else:
                stdout(f'{key:>30} -> {value}')

    data_path = os.path.abspath(config['data-folder'])
    stdout(f'using data path: {data_path}')
    os.makedirs(data_path, exist_ok=True)

    prepare_output_folders(config, data_path)
    setup_mqtt_clients(config, shared_state, data_path)

    signal.signal(signal.SIGINT, signal_handler(shared_state))
    start_time = time.time()
    last_message_count = 0
    feedback_period = config['console-feedback-period-seconds']

    performance_client, performance_topic = setup_performance_logging(config)

    while True:
        time.sleep(feedback_period)

        current_time, elapsed_time, total_message_count, messages_per_second_total, \
        messages_per_second_recent, elapsed_time_hours = calculate_performance_metrics(
            shared_state, start_time, last_message_count, feedback_period)

        last_message_count = total_message_count
        performance_details = []

        for stream_idx in range(len(shared_state.streams)):
            performance_detail = process_stream_performance(shared_state, stream_idx, config)
            if performance_detail:
                performance_details.append(performance_detail)

        performance_message = {
            'elapsed_time_hours': elapsed_time_hours,
            'totalMessageCount': total_message_count,
            'messages_per_second_total': messages_per_second_total,
            'messages_per_second_recent': messages_per_second_recent,
            'performance_details': performance_details,
        }

        publish_performance_message(performance_client, performance_topic, performance_message)
