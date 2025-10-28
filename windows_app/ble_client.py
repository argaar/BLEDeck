import asyncio
import re
from bleak import BleakClient

DEVICE_NAME = "BLEDeck"
CHAR_TX_UUID = "BEB5483E-36E1-4688-B7F5-EA07361B26A8"
CHAR_RX_UUID = "EAB5483E-36E1-4688-B7F5-EA07361B26A9"

current_profile_index = 0

client: BleakClient | None = None

async def send_ble(msg: str):
    print(f"→ {msg}")
    await client.write_gatt_char(CHAR_RX_UUID, msg.encode())

async def send_current_profile():
    global current_profile_index
    msg = f"SET_PROFILE:{current_profile_index}"
    await send_ble(msg)
    print(f"🔁 Resent profile state → {msg}")

async def handle_notification(sender, data):
    global last_received_seq_from_esp
    msg = data.decode("utf-8").strip()
    print(f"← {msg}")

    if msg.startswith("ACK:"):
        pass
    elif msg.startswith("PING"):
        await send_ble("ACK:PING")
    elif msg.startswith("PROFILE:"):
        print(f"📁 Current profile: {msg}")
    else:
        try:
            revc_msg = msg.split(';')
            profile = revc_msg[0]
            payload = revc_msg[1]
            print(f"ℹ️ Working on Profile: {profile}")
            print(f"ℹ️ Received: {payload}")
        except:
            print(f"ℹ️ Unhaldled message: {msg}")

async def connect_and_run(address):
    global client
    client = BleakClient(address)
    await client.connect()
    print(f"✅ Connected to {address}")
    await client.start_notify(CHAR_TX_UUID, handle_notification)
    await send_ble("PING")
    while True:
        await asyncio.sleep(1)

async def main():
    from bleak import BleakScanner
    print("🔍 Scanning for BLEDeck...")
    devices = await BleakScanner.discover()
    target = next((d for d in devices if DEVICE_NAME in d.name), None)
    if not target:
        print("❌ Device not found")
        return
    await connect_and_run(target.address)

if __name__ == "__main__":
    asyncio.run(main())
