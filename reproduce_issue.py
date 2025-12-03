import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def reproduce():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Start procedure
        start_payload = {
            "username": "Mikameel",
            "procedure_id": "pizza_custom",
            "source_id": "Mikameel",
            "policy": "replace"
        }
        print(f"Starting procedure with payload: {start_payload}", flush=True)
        response = await client.post("/api/v2/procedures/start", json=start_payload)
        print(f"Start response: {response.status_code} {response.text}", flush=True)

        if response.status_code != 200:
            print("Failed to start procedure, cannot proceed with stop test.", flush=True)
            return

        # Stop procedure
        stop_payload = {
            "username": "Mikameel",
            "procedure_id": "pizza_custom",
            "source_id": "Mikameel",
            "policy": "replace"
        }
        print(f"Stopping procedure with payload: {stop_payload}", flush=True)
        response = await client.post("/api/v2/procedures/stop", json=stop_payload)
        print(f"Stop response: {response.status_code} {response.text}", flush=True)

if __name__ == "__main__":
    asyncio.run(reproduce())
