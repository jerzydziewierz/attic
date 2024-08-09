import gradio as gr
import paho.mqtt.client as mqtt
import json
import time
import threading

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
        f"{latest_data['messages_per_second_total']:.2f}",
        f"{latest_data['messages_per_second_recent']:.2f}",
    )

def update_performance_details():
    details = latest_data['performance_details']
    rows = []
    for detail in details:
        rows.append([
            detail['stream_prefix'],
            f"{detail['stream_idx']}",
            f"{detail['utilisation_ratio']:.2f}%",
            f"{detail['messages_this_channel']}",
            detail['last_rx_timestamp_iso'],
            "Connected" if detail['is_connected'] else "Disconnected"
        ])
    return rows

# Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# Attic Performance Monitor")
    
    with gr.Row():
        elapsed_time = gr.Textbox(label="Elapsed Time (hours)")
        total_messages = gr.Textbox(label="Total Messages")
        msgs_per_sec_total = gr.Textbox(label="Messages/sec (Total)")
        msgs_per_sec_recent = gr.Textbox(label="Messages/sec (Recent)")

    performance_table = gr.Dataframe(
        headers=["Stream Prefix", "Stream Index", "Utilization", "Messages", "Last Received", "Status"],
        label="Performance Details"
    )

    demo.load(update_stats, outputs=[elapsed_time, total_messages, msgs_per_sec_total, msgs_per_sec_recent], every=1)
    demo.load(update_performance_details, outputs=[performance_table], every=1)

if __name__ == "__main__":
    demo.launch()