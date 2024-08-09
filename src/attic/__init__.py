import argparse  # for parsing command line arguments
import yaml  # for parsing the configuration file
import os  # for creating folders
import signal  # for handling signals
import sqlite3  # for saving the data
import threading  # for running multiple threads
import time  # for performance measurement
import datetime  # for storage addressing
import pytz  # "python time zone" library for precision time zone handling
import typing  # for type hints
from typing import Callable, Any, List, Dict
import pathlib
from .safetimestring import datetime_to_safestring, safestring_to_datetime, timefolders
import json

from paho.mqtt import client as mqtt

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

# The work function generator, to create the function that will be called "on message" #
########################################################################################

def make_on_message_callback(
        shared_state: SharedState,
        q_stream_idx: int,
        intended_topic: str,
        q_stream_path: str = "",
        log_rotation_time: int = 600):

    # at this point, the SharedState.streams[q_stream_idx]=dict() needs to be already there, created by the caller.
    # this is because this function cannot assume the order in which the threads will be created.
    debug_mode = True
    if debug_mode:
        stdout(f'{len(shared_state.streams)=} {q_stream_idx=}')
    shared_state.streams[q_stream_idx] = dict(
        messageCount=0,
        intendedTopic=intended_topic,
        lastMessage=None,
        sqlite_cursor=None,
        sqlite_connection=None,
        next_rotation_time=0,
        stop_request=False,
        stop_request_ack=False,
        process_start_time=0.0,
        process_end_time=time.time(),  # todo: convert to datetime.datetime.now() format everywhere.
        previous_end_time=0.0,
        totalIdleTime=0.0,
        totalProcessingTime=0.0,
    )

    # closure: captures locals, in particular the q_stream_idx, intendedTopic, q_stream_path, logRotationTime
    def curried_on_message(_1, _2, msg):
        shared_state.streams[q_stream_idx]['process_previous_start_time'] = \
            shared_state.streams[q_stream_idx]['process_start_time']
        shared_state.streams[q_stream_idx]['process_start_time'] = time.time()
        shared_state.streams[q_stream_idx]['previous_end_time'] = shared_state.streams[q_stream_idx][
            'process_end_time']

        # builds new database connection as needed.
        def renew_database_link() -> typing.Tuple[sqlite3.Cursor, sqlite3.Connection]:
            pathlib.Path(q_stream_path).mkdir(parents=True, exist_ok=True)
            safedatestring = datetime_to_safestring(datetime.datetime.now(tz=pytz.UTC))
            file_name = f'{safedatestring}.sqlite'
            # prepare folder name
            # folder per day should be sufficient for this application
            full_folder_name = timefolders(q_stream_path, datetime.datetime.now(tz=pytz.UTC))
            full_folder_name.mkdir(parents=True, exist_ok=True)
            sqlite_db_path = full_folder_name.joinpath(file_name)
            stdout(f'{q_stream_idx=} | topic={shared_state.configs[q_stream_idx]['prefix']} |  creating new file {sqlite_db_path}')
            sqlite_connection_r = sqlite3.connect(sqlite_db_path)
            sqlite_cursor_r = sqlite_connection_r.cursor()
            sqlite_cursor_r.execute(
                'CREATE TABLE IF NOT EXISTS data (reception_timestamp INTEGER, topic TEXT, payload BLOB)')
            # this is so that at read time, the data can be quickly filtered by topic.
            sqlite_cursor_r.execute(
                'CREATE INDEX IF NOT EXISTS topics ON data (topic)')
            sqlite_connection_r.commit()
            # save the cursor and connection to the shared state for use by interested parties.
            shared_state.streams[q_stream_idx]['sqlite_cursor'] = sqlite_cursor_r
            shared_state.streams[q_stream_idx]['sqlite_connection'] = sqlite_connection_r
            # important: set the expiration time for the next rotation
            next_rotation_time_r = time.time() + log_rotation_time
            shared_state.streams[q_stream_idx]['next_rotation_time'] = next_rotation_time_r
            return sqlite_cursor_r, sqlite_connection_r

        try:
            # the case of the cursor being None is a special case.
            if shared_state['streams'][q_stream_idx]['sqlite_cursor'] is None:
                # create the cursor and connection.
                # this is because the object must be created and used in the same thread.
                if not (shared_state['streams'][q_stream_idx]['stop_request']):
                    sqlite_cursor, sqlite_connection = renew_database_link()
                else:
                    # except if the stop request has been issued, in which case, ignore the message and return.
                    sqlite_cursor = None
                    sqlite_connection = None
                    shared_state['streams'][q_stream_idx]['stop_request_ack'] = True
                    return  # early return (ignores message). Note that such implementation means that it may take forever to exit the program, as it can only exit when a message is received.
            else:  # the cursor is not None, the typical happy case.
                # load the cursor and connection from the shared state.
                sqlite_cursor = shared_state['streams'][q_stream_idx]['sqlite_cursor']
                sqlite_connection = shared_state['streams'][q_stream_idx]['sqlite_connection']

                # if the stop request has been issued, make an effort to gracefully stop the database.
                if shared_state['streams'][q_stream_idx]['stop_request']:
                    sqlite_connection.commit()
                    sqlite_cursor.close()
                    sqlite_connection.close()
                    shared_state['streams'][q_stream_idx]['sqlite_cursor'] = None
                    shared_state['streams'][q_stream_idx]['sqlite_connection'] = None
                    shared_state['streams'][q_stream_idx]['stop_request_ack'] = True
                    return

                # Regular operation. The music doesn't stop! Make an effort to save the data.
                # but, first, check for rotation time
                next_rotation_time = shared_state['streams'][q_stream_idx]['next_rotation_time']
                if time.time() > next_rotation_time:
                    # rotate the log
                    print(f'{q_stream_idx=} rotating log...')
                    sqlite_connection.commit()
                    sqlite_cursor.close()
                    sqlite_connection.close()
                    shared_state['streams'][q_stream_idx]['sqlite_cursor'] = None
                    shared_state['streams'][q_stream_idx]['sqlite_connection'] = None
                    # re-open the log with next file name. This will give us a fresh database connection.
                    sqlite_cursor, sqlite_connection = renew_database_link()
            # at this point, we should have a good sqlite_cursor and sqlite_connection
            # write the data to the database
            topic = msg.topic
            payload = msg.payload  # bytes ! important. Do not decode. Store the bytes as-is, as it may be e.g. an avro packet or other binary data.
            timestamp_unix = int(1e6 * time.time())  # microseconds since epoch
            timestamp_iso_string = datetime.datetime.now(tz=pytz.UTC).isoformat(timespec='microseconds')
            shared_state['streams'][q_stream_idx]['lastRxTimestamp_unix'] = timestamp_unix
            shared_state['streams'][q_stream_idx]['lastRxTimestamp_iso_string'] = timestamp_iso_string
            if sqlite_cursor is not None:
                sqlite_cursor.execute("INSERT INTO data VALUES (?, ?, ?)", (timestamp_unix, topic, payload))
                # sqlite_connection.commit()  # no need to commit as this is done in the rotation code
                # finally, internal performance monitoring.
                shared_state['totalMessageCount'] += 1
                shared_state['streams'][q_stream_idx]['messageCount'] += 1
                shared_state['streams'][q_stream_idx]['process_end_time'] = time.time()
                # compute idle time
                q_idle_time = shared_state['streams'][q_stream_idx]['process_start_time'] - \
                              shared_state['streams'][q_stream_idx]['previous_end_time']
                # compute processing time
                q_processing_time = shared_state['streams'][q_stream_idx]['process_end_time'] - \
                                    shared_state['streams'][q_stream_idx]['process_start_time']
                # store the idle time and processing time
                # this is so that I can estimate the leftover node capacity.
                shared_state['streams'][q_stream_idx]['totalIdleTime'] += q_idle_time
                shared_state['streams'][q_stream_idx]['totalProcessingTime'] += q_processing_time

            else:
                print(f'{q_stream_idx=} sqlite_cursor is None, ignoring message. This is probably a bug.')

        except Exception as ex:
            print(f'error in on_message: {ex}')
            # get the line of the source of exception:
            import traceback
            print(traceback.format_exc())

            print(f'message lost, not retrying.')

    return curried_on_message


def make_on_connect(topics):
    def curried_on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 5:
            stdout('mqtt broker rejected connection. This is probably because the username and password are incorrect.')
            stdout('continue...')
        else:
            stdout(f'connected to mqtt broker with result code {reason_code} and flags {flags} |', end='')
            # subscribe to the topics
            for topic in topics:
                client.subscribe(topic)
                stdout(f'| subscribed to {topic} |', end='')
            stdout()

    return curried_on_connect


def on_disconnect(client, userdata, flags, reason_code, properties):
    stdout(f'disconnected from mqtt broker with reason code {reason_code} and flags {flags}')
    # if disconnected, reconnect,
    # we need to handle this gracefully.

    if reason_code != 0:
        pass


# prepare to capture break signal
###############################################################################################
def signal_handler(shared_state: SharedState):
    def handler(sig, frame):
        # unregister itself so that repeated ctrl-c will not trigger this function again.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        # we need a graceful stop so that the data in the sqlite database is not corrupted and readable.
        # this enables reading partially captured data.
        stdout('Abort signal received! Attempting a graceful stop, hold on ...')
        for stream_idx2 in range(len(shared_state.streams)):
            try:
                stdout(f'sending stop signal to {stream_idx2=}...')
                # note that there must be a mqtt message coming in for the stop request to be processed
                shared_state.streams[stream_idx2]['stop_request'] = True
                while not shared_state.streams[stream_idx2]['stop_request_ack']:
                    # if ctrl-c is pressed again during this time, the program will exit immediately.
                    time.sleep(0.2)
                    stdout('.', end='', flush=True)
            except Exception as ex1:
                stdout(f'error {ex1} when stopping sqlite on {stream_idx2=}, not retrying.')
                pass

        for client in shared_state.clients:
            try:
                stdout(f'stopping client {client} ...')
                client.loop_stop()
                client.disconnect()
            except Exception as ex2:
                stdout(f'error {ex2} when stopping client {client}, not retrying.')
                pass

        from sys import exit
        exit(0)
    
    return handler


def run():
    stdout("starting attic, version 0.0.1")

    # parse arguments:
    #########################################################################################

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default='config/config.yaml',
                        help='fully qualified path to the configuration file, yaml format')
    args = parser.parse_args()

    if args.config is None:
        stdout('no config file specified. cannot continue.')
        exit(1)

    # prepare shared state:
    #########################################################################################

    shared_state = SharedState()
    lock = threading.Lock()

    # load configuration:
    #########################################################################################

    config_path = os.path.abspath(args.config)
    stdout(f'using configuration from: {config_path}')

    try:
        with open(config_path, 'r') as stream:
            try:
                config = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                stdout(exc)
    except FileNotFoundError as no_config_file:
        stdout(f'error: {no_config_file}')
        exit(1)

    stream_count = len(config['streams'])
    stdout(f'got {stream_count} streams')

    for stream in range(stream_count):
        stdout(f'stream {stream}:')
        for key in config["streams"][stream].keys():
            if key == 'password':
                stdout(f'{key:>30} -> {"*" * len(config["streams"][stream][key])}')
            else:
                stdout(f'{key:>30} -> {config["streams"][stream][key]}')

    # prepare output folders:
    #########################################################################################

    data_path = os.path.abspath(config['data-folder'])
    stdout(f'using data path: {data_path}')
    os.makedirs(data_path, exist_ok=True)

    # for each stream, create a folder with that prefix. If there is no prefix, use stream number
    for stream in range(stream_count):
        folder_prefix = config['streams'][stream]['prefix']
        if folder_prefix == '':
            folder_prefix = str(stream)
        folder_suffix = config['streams'][stream]['suffix']
        folder_name = folder_prefix + folder_suffix
        stream_path = os.path.join(data_path, folder_name)
        stdout(f'creating {stream_path}')
        os.makedirs(stream_path, exist_ok=True)


    # for each stream, create mqtt client and subscribe to topic
    for stream_idx in range(stream_count):
        stream_config = config['streams'][stream_idx]
        shared_state.add_config(stream_config)

        # prepare path to save the data to:
        folder_prefix = config['streams'][stream_idx]['prefix']
        if folder_prefix == '':
            raise ValueError('folder prefix cannot be empty.')
        folder_suffix = config['streams'][stream_idx]['suffix']
        folder_name = folder_prefix + folder_suffix
        stream_path = os.path.join(data_path, folder_name)

        # create the mqtt client and pass on the curried on_message function

        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        shared_state.add_client(mqtt_client)
        shared_state.add_stream(dict())

        # TODO: Do not connect here. Connect in the root thread.
        on_connect = make_on_connect([stream_config['topic']])
        mqtt_client.on_connect = on_connect  # this will also subscribe to the topic
        mqtt_client.on_disconnect = on_disconnect  # update: now only handle re-connecting in the root thread.

        # this pattern is called "making a closure",
        # that is, a function that returns a function that closes over some variables provided from the outer scope
        this_on_message = make_on_message_callback(
            shared_state,
            stream_idx,
            intended_topic=stream_config['topic'],
            q_stream_path=stream_path,
            log_rotation_time=stream_config['file-rotation-time-seconds']
        )
        mqtt_client.on_message = this_on_message
        if stream_config['user'] != "":
            mqtt_client.username_pw_set(stream_config['user'], stream_config['password'])
        mqtt_client.connect(stream_config['mqtt-broker-address'], stream_config['mqtt-broker-port'], 10)

        # ! This starts the mqtt client in a separate thread.
        mqtt_client.loop_start()

    # final preparation before starting the main loop
    ##############################################################################################
    signal.signal(signal.SIGINT, signal_handler(shared_state))
    start_time = time.time()

    last_message_count = 0
    feedback_period = config['console-feedback-period-seconds']

    if config['log-performance']:
        performance_topic = config['log-performance-stream']['topic']
        performance_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if config['log-performance-stream']['user'] != "":
            performance_client.username_pw_set(config['log-performance-stream']['user'],
                                               config['log-performance-stream']['password'])
        performance_client.connect(config['log-performance-stream']['mqtt-broker-address'],
                                   config['log-performance-stream']['mqtt-broker-port'], 60)
        performance_client.loop_start()
    else:
        performance_client = None
        performance_topic = None

    # The Forever loop
    ##############################################################################################
    while True:
        # The main thread is a monitoring thread. The real work is done in the mqtt client threads.
        time.sleep(feedback_period)

        current_time = time.time()
        elapsed_time = current_time - start_time
        totalMessageCount = shared_state.totalMessageCount
        messages_per_second_total = totalMessageCount / elapsed_time
        messages_per_second_recent = (totalMessageCount - last_message_count) / feedback_period
        last_message_count = totalMessageCount
        elapsed_time_hours = elapsed_time / 3600
        performance_details = []
        # compute idle time to total time ratio, per stream
        # this is important to estimate the leftover node capacity.
        for stream_idx in range(len(shared_state.streams)):
            idle_time = shared_state.streams[stream_idx]['totalIdleTime']
            processing_time = shared_state.streams[stream_idx]['totalProcessingTime']
            total_time = idle_time + processing_time
            if total_time > 0:
                idle_time_ratio = idle_time / total_time
                utilisation_ratio = 100 * (1.0 - idle_time_ratio)
                # stdout(f"{stream_idx=} {utilisation_ratio=:06.3f} %")
                stream_connected = shared_state.clients[stream_idx].is_connected()
                if not stream_connected:
                    stdout(f"stream {stream_idx} is not connected, attempting to reconnect ...")
                    try:
                        # trying to work the client from another thread is risky, do not do this now.
                        h_client = shared_state.clients[stream_idx]
                        stream_config = config['streams'][stream_idx]
                        time.sleep(0.1)
                        h_client.loop_stop()
                        time.sleep(0.1)
                        h_client.disconnect()
                        time.sleep(0.1)
                        # now, connect again with refreshed settings
                        if stream_config['user'] != "":
                            h_client.username_pw_set(username=stream_config['user'],
                                                     password=stream_config['password'])
                        time.sleep(0.1)
                        on_connect = make_on_connect([stream_config['topic']])
                        h_client.on_connect = on_connect  # this will also subscribe to the topic

                        h_client.connect(host=stream_config['mqtt-broker-address'],
                                         port=stream_config['mqtt-broker-port'],
                                         keepalive=10)
                        time.sleep(0.1)
                        h_client.loop_start()
                        time.sleep(0.1)
                        # h_client.reconnect()
                        # !! After the server reboots, it doesn't know
                        # !! what the client would like to subscribe to. We need to tell it again.
                        # !! Update: this is now done in curried on_connect (it is curried with the topics to subscribe to)
                    except Exception as ex:
                        stdout(f"error {ex} when reconnecting stream {stream_idx}, not retrying.")
                    # after this, do not update the status yet, report the state as seen before the attempt to reconnect.

                performance_detail = dict(
                    stream_prefix=config['streams'][stream_idx]['prefix'],
                    stream_idx=stream_idx,
                    utilisation_ratio=utilisation_ratio,
                    messages_this_channel=shared_state.streams[stream_idx]['messageCount'],
                    last_rx_timestamp_unix=shared_state.streams[stream_idx]['lastRxTimestamp_unix'],
                    last_rx_timestamp_iso=shared_state.streams[stream_idx]['lastRxTimestamp_iso_string'],
                    is_connected=stream_connected,
                )
                performance_details.append(performance_detail)
            else:
                pass

        # stdout(
        #     f"{elapsed_time_hours=:0.1f} hours, {totalMessageCount=},
        #     {messages_per_second_total=:0.1f}/sec, {messages_per_second_recent=:0.1f}/sec")
        # print('.', end='', )

        if performance_client is not None:
            performance_message = dict(
                elapsed_time_hours=elapsed_time_hours,
                totalMessageCount=totalMessageCount,
                messages_per_second_total=messages_per_second_total,
                messages_per_second_recent=messages_per_second_recent,
                performance_details=performance_details,
                )
            performance_client.publish(
                topic=performance_topic,
                payload=json.dumps(performance_message)
                )
