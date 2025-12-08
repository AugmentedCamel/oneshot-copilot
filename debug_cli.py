import asyncio
import httpx
import json
import sys


# Try to import rich for pretty printing, fallback to print if not available
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

async def get_status(url="http://localhost:8000/api/v2/debug/status"):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error fetching status: {e}")
        return None

def print_status(data):
    if not data:
        return

    if HAS_RICH:
        console = Console()
        
        # Sources Table
        source_table = Table(title="Registered Sources")
        source_table.add_column("ID", style="cyan")
        source_table.add_column("Name", style="magenta")
        source_table.add_column("Type", style="green")
        source_table.add_column("Config", style="yellow")
        
        for source in data.get("sources", []):
            source_table.add_row(
                source.get("id"),
                source.get("name"),
                source.get("type"),
                str(source.get("config"))
            )
        console.print(source_table)
        
        # Procedures
        proc_data = data.get("procedures", {})
        
        # Active Sessions
        active_table = Table(title="Active Sessions")
        active_table.add_column("Username", style="cyan")
        active_table.add_column("Procedure", style="magenta")
        active_table.add_column("Step", style="green")
        
        for username, sessions in proc_data.get("active_sessions", {}).items():
            for session in sessions:
                proc = session.get("procedure", {})
                proc_id = proc.get("id", "N/A") if proc else "N/A"
                step_idx = session.get("current_step_index", -1)
                active_table.add_row(username, proc_id, str(step_idx))
                
        console.print(active_table)
        
        # User Sources
        us_table = Table(title="User Source Mappings")
        us_table.add_column("Username", style="cyan")
        us_table.add_column("Source ID", style="magenta")
        
        for username, source_id in proc_data.get("user_sources", {}).items():
            us_table.add_row(username, source_id)
            
        console.print(us_table)
        
    else:
        print(json.dumps(data, indent=2))

async def main(url):
    data = await get_status(url)
    print_status(data)

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v2/debug/status"
    asyncio.run(main(url))
