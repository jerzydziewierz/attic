import gradio as gr
import paho.mqtt.client as mqtt
import json
import time
import threading
from datetime import datetime, timezone
import math

# Global variables to store the latest performance data
latest_data = {
    "elapsed_time_hours": 0,
    "totalMessageCount": 0,
    "messages_per_second_total": 0,
    "messages_per_second_recent": 0,
    "performance_details": []
}

# MQTT client setup
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Connected with result code {rc}")
    client.subscribe("attic/performance")


def on_message(client, userdata, msg):
    global latest_data
    try:
        latest_data = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        print("Error decoding JSON message")


client.on_connect = on_connect
client.on_message = on_message

# Connect to the MQTT broker
client.connect("localhost", 1883, 60)

# Start the MQTT client loop in a separate thread
threading.Thread(target=client.loop_forever, daemon=True).start()


def update_stats():
    return (
        f"{latest_data['elapsed_time_hours']:.2f}",
        f"{latest_data['totalMessageCount']}",
        latest_data['messages_per_second_total'],
        f"{latest_data['messages_per_second_recent']:.2f}",
    )


def update_performance_details():
    details = latest_data['performance_details']
    rows = []
    current_time = datetime.now(timezone.utc)
    for detail in details:
        last_rx_time = datetime.fromisoformat(detail['last_rx_timestamp_iso'])
        time_since_last_update = current_time - last_rx_time
        seconds_since_last_update = time_since_last_update.total_seconds()
        
        status = "Connected" if detail['is_connected'] else "Disconnected"
        warning = "🔴" if seconds_since_last_update > 10 else "🟢"
        
        rows.append([
            detail['stream_prefix'],
            f"{detail['stream_idx']}",
            f"{detail['utilisation_ratio']:.2f}%",
            f"{detail['messages_this_channel']}",
            f"{seconds_since_last_update:.1f}s ago",
            f"{status} {warning}"
        ])
    return rows


# Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# Attic Performance Monitor")

    with gr.Row():
        elapsed_time = gr.Textbox(label="Elapsed Time (hours)")
        total_messages = gr.Textbox(label="Total Messages")
        msgs_per_sec_total = gr.Gauge(label="Messages/sec (Total)", minimum=0, maximum=100, show_label=True)
        msgs_per_sec_recent = gr.Textbox(label="Messages/sec (Recent)")

    performance_table = gr.Dataframe(
        headers=["Stream Prefix", "Stream Index", "Utilization", "Messages", "Time Since Last Update", "Status"],
        label="Performance Details"
    )

    demo.load(update_stats, outputs=[elapsed_time, total_messages, msgs_per_sec_total, msgs_per_sec_recent], every=1)
    demo.load(update_performance_details, outputs=[performance_table], every=1)

if __name__ == "__main__":
    demo.launch()
