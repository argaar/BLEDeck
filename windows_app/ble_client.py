import asyncio
from bleak import BleakClient

DEVICE_NAME = "BLEDeck"
CHAR_TX_UUID = "BEB5483E-36E1-4688-B7F5-EA07361B26A8"
CHAR_RX_UUID = "EAB5483E-36E1-4688-B7F5-EA07361B26A9"

current_profile_index = 0

client: BleakClient | None = None

async def send_ble(msg: str):
    print(f"→ {msg}")
    if client is not None:
        await client.write_gatt_char(CHAR_RX_UUID, msg.encode())
    else:
        print("❌ BLE client is not connected.")

async def connect_and_run(address):
    global client
    client = BleakClient(address)
    await client.connect()
    print(f"✅ Connected to {address}")
    await send_ble("PING")
    while True:
        await asyncio.sleep(1)

async def main():
    from bleak import BleakScanner
    print("🔍 Scanning for BLEDeck...")
    devices = await BleakScanner.discover()
    target = next((d for d in devices if d.name and DEVICE_NAME in d.name), None)
    if not target:
        print("❌ Device not found")
        return
    await connect_and_run(target.address)

if __name__ == "__main__":
    asyncio.run(main())
