import argparse
import requests
import sys
import json

def ask_question(question, username=None, session_id=None, url="http://localhost:8000"):
    endpoint = f"{url}/api/v2/agent/assist"
    
    payload = {
        "query": question
    }
    
    if session_id:
        payload["session_id"] = session_id
    elif username:
        payload["username"] = username
    else:
        print("Error: Must provide either --user or --session-id")
        sys.exit(1)
    
    try:
        print(f"Sending question to {endpoint}...")
        response = requests.post(endpoint, json=payload)
        response.raise_for_status()
        
        result = response.json()
        print("\nResponse from Agent:")
        print("-" * 40)
        if isinstance(result, dict):
            print(json.dumps(result, indent=2))
        else:
            print(result)
        print("-" * 40)
        
    except requests.exceptions.HTTPError as e:
        print(f"Error: {e}")
        if e.response is not None:
            print(f"Details: {e.response.text}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {url}. Is the server running?")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask a question to the Oneshot Copilot Agent.")
    parser.add_argument("question", help="The question to ask.")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user", help="The username (e.g., Mikameel)")
    group.add_argument("--session-id", help="The Memory Service Session ID")
    
    parser.add_argument("--url", default="http://localhost:8000", help="The base URL of the Oneshot Copilot (default: http://localhost:8000)")
    
    args = parser.parse_args()
    
    ask_question(args.question, username=args.user, session_id=args.session_id, url=args.url)
