# !! This is the AIDER demo branch -- not for production.


# Attic the sensor data logging system 

This is a simple system to log sensor data from a MQTT broker to a sqlite database.

* Intended for use in local network
* Intended for use with small data
  * 500 messages/sec takes approx. 0.5% of CPU on a modern desktop
* Configurable using yaml 
* Hackable in python. If you need a new filter, just write it in python.
* self-reports it's performance
* supports multiple streams in separate threads: fully takes advantage of multi-core systems. 
* However, it is mainly intended to log everything that happened on a given mqtt broker.
* auto rotates the log files by time, so that they are easily slice able and transportable
* the log file is a sqlite database, readable by all the popular tools incl. pandas


# How do I get set up?

It is intended to be ran as a service, either on the same node, or on a node adjecent to the mqtt broker node.

# Key concepts

### "Stream" 

For a lack of a better name, stream is a single thread that listens to specific topic and then saves the events to it's configured database.

One stream can listen to a wildcard topic, e.g. `#` or `+/+/+/+`; in this case, the stream will save all the events that match the topic.

However, if you have a lot of messages per topic, you may want to use the MQTT's strongest side: the broker will do the load balancing for you.

Simply create a stream for each topic, and then you can use a multicore system or even multiple nodes to process the data.

### Log file rotation

Obviously, if you save generated data for a long time, you will have a lot of data. Having very large log files can be problematic.

Here, the problem is addressed by:
 
* Placing output of a stream in dedicated folder, as configured in the config file

* Naming each file by its creation time stamp in unix format

* Starting a new file every period, where period is also configured in the config file

* preventing the folder clog-up by creating a new folder per day
 
### Timestamp

For this work, i select to use unix epoch time in microseconds,

that is, seconds * 1e6

This is enough of resolution that nearly every message will get a unique timestamp.

Note that the "reception_timestamp", is, of course, the local timestamp of the log saver, and not the timestamp of the event that happened at the source.

# What does it do exactly?

I have made an effort to comment the code, as far as practicable, 

however, since it uses threads, the execution is a bit nonlinear.

The general idea is as follows:

1.Read the configuration from config.yaml

See config.example.yaml for an example. The names of fields in the config should be self-explanatory.

2.Set up a global state dict, "SharedState".

3.Create an "on message" closure function that captures the configuration settings, using a closure-generating-function (`cgf`) named `make_onmessage_callback()`

The `cgf` sets up the storage folder, and then defines the closure.

The resulting closure function is passed on to the mqtt client library.

3.Start the mqtt connection, and pass the closure function to the mqtt client library.

4.The closure function is called by the mqtt client library, in the mqtt client thread, when a message is received and it will:

* Check if the system is in shutdown mode.
    * if yes, it will attempt to flush the database, and when successful, exit the function early
* Check if the file rotation timer has expired
    * if yes, force flushing the messages and close the database. 
* Check if the database link is open
    * if not, open it with a new creation timestamp, and store the link in the shared state dict.
* Add the message to the database, without flushing it. 
* SQLite decides when to flush the messages -- by default, sqlite flushes the messages to disk every 1000 messages, or every 1 second, whichever comes first.

5.That's it. So simple. Profit!

Generally, this is intended to be run as a system service, forever. However, I have made extra effort to support graceful shutdown so that the data can be collected for short periods of time, and aborted at any time. 

# Future work

* Verify that the log file rotation doesn't slow down the system too much. If that is a problem, the code would probably need to be rebuilt. At this time, it appears fast enough for my needs.
* Add support for Avro packets coming from the MQTT broker. This would be a good way to save space.
* Port this to async rust. I have a feeling that this functionality would be a good fit for async rust, and it would be a good learning experience for me.


