import paho.mqtt.client as mqtt
import json
import time
import argparse


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Connected with result code {rc}")


def main():
    parser = argparse.ArgumentParser(description="MQTT Counter Publisher")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--topic", default="test/counter", help="MQTT topic to publish to")
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    client.connect(args.broker, args.port, 60)
    client.loop_start()

    counter = 1
    try:
        while True:
            message = json.dumps({"count": counter})
            client.publish(args.topic, message)
            print(f"Published: {message}")
            counter += 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
