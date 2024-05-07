import argparse  # for parsing command line arguments
import pyyaml  # for parsing the configuration file
import os  # for creating folders
import signal  # for handling signals
import sqlite3  # for saving the data
import threading  # for running multiple threads
import time  # for performance measurement
import datetime  # for storage addressing
import pytz  # "python time zone" library for precision time zone handling
import typing  # for type hints
from typing import Callable, Any

from paho.mqtt import client as mqtt

print("starting hyattic, version 0.0.1")



# parse arguments:
#########################################################################################

parser = argparse.ArgumentParser()
parser.add_argument('--config', type=str, default='config.yaml', help='fully qualified path to the configuration file, yaml format')
args = parser.parse_args()

if args.config is None:
    print('no config file specified. cannot continue.')
    exit(1)

# prepare shared state:
#########################################################################################

# note to the purist: I am aware of the GIL. I am not worried about it here:
# on my machine, GIL with modification of global state, switches approx. 20e6 times per second,
# and the log saver generally does not need to run at super-realtime.
# Hence, I am not worried about the performance impact of this code

global shared_state
shared_state = {'totalMessageCount': 0, 'streams': []}
lock = threading.Lock()

# load configuration:
#########################################################################################

import yaml

config_path = os.path.abspath(args.config)
print(f'using configuration from: {config_path}')

with open(config_path, 'r') as stream:
    try:
        config = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        print(exc)

stream_count = len(config['streams'])
print(f'got {stream_count} streams')

for stream in range(stream_count):
    print(f'stream {stream}:')
    for key in config["streams"][stream].keys():
        if key == 'password':
            print(f'{key:>30} -> {"*" * len(config["streams"][stream][key])}')
        else:
            print(f'{key:>30} -> {config["streams"][stream][key]}')


# prepare output folders:
#########################################################################################

data_path = os.path.abspath(config['data-folder'])
print(f'using data path: {data_path}')
os.makedirs(data_path, exist_ok=True)

# for each stream, create a folder with that prefix. If there is no prefix, use stream number
for stream in range(stream_count):
    folder_prefix = config['streams'][stream]['prefix']
    if folder_prefix == '':
        folder_prefix = str(stream)
    folder_suffix = config['streams'][stream]['suffix']
    folder_name = folder_prefix + folder_suffix
    stream_path = os.path.join(data_path, folder_name)
    print(f'creating {stream_path}')
    os.makedirs(stream_path, exist_ok=True)

