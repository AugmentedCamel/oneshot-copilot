import asyncio
import httpx
import json

MEMORY_SERVICE_URL = "http://localhost:8040"  # Assuming this is the URL from config

async def inspect_procedure():
    async with httpx.AsyncClient(base_url=MEMORY_SERVICE_URL) as client:
        print(f"Fetching 'kitchen_recipes' from {MEMORY_SERVICE_URL}...")
        try:
            response = await client.get("/procedures/kitchen_recipes")
            if response.status_code == 200:
                data = response.json()
                # Handle wrapped response if necessary (based on strategy code)
                if "definition" in data:
                    data = data["definition"]
                
                print(f"Successfully fetched 'kitchen_recipes'.")
                print(f"Internal ID found in JSON: {data.get('id')}")
                print(f"Name found in JSON: {data.get('name')}")
            else:
                print(f"Failed to fetch 'kitchen_recipes': {response.status_code} {response.text}")
        except Exception as e:
            print(f"Error connecting to Memory Service: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_procedure())
