import gradio as gr
import paho.mqtt.client as mqtt
import json
import time
import threading
from datetime import datetime, timezone
import math
import plotly.graph_objects as go

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


def create_gauge(value, max_value=100):
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "Messages/sec (Total)"},
        gauge = {
            'axis': {'range': [None, max_value]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, max_value*0.6], 'color': "lightgray"},
                {'range': [max_value*0.6, max_value*0.8], 'color': "gray"},
                {'range': [max_value*0.8, max_value], 'color': "darkgray"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': max_value*0.9
            }
        }
    ))
    fig.update_layout(height=300)
    return fig

def update_stats():
    gauge_value = min(latest_data['messages_per_second_total'], 100)
    gauge_plot = create_gauge(gauge_value)
    return (
        f"{latest_data['elapsed_time_hours']:.2f}",
        f"{latest_data['totalMessageCount']}",
        gauge_plot,
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
        msgs_per_sec_total = gr.Plot(label="Messages/sec (Total)")
        msgs_per_sec_recent = gr.Textbox(label="Messages/sec (Recent)")

    performance_table = gr.Dataframe(
        headers=["Stream Prefix", "Stream Index", "Utilization", "Messages", "Time Since Last Update", "Status"],
        label="Performance Details"
    )

    demo.load(update_stats, outputs=[elapsed_time, total_messages, msgs_per_sec_total, msgs_per_sec_recent], every=1)
    demo.load(update_performance_details, outputs=[performance_table], every=1)

if __name__ == "__main__":
    demo.launch()
