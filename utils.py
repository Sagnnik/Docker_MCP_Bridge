from typing import Optional, Dict, Any
import json

def parse_sse_json(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Given an SSE response like:
        event: message
        id: ...
        data: {...JSON...}

    extract and return the JSON object from the first 'data: ' line.
    """
    for line in response_text.splitlines():
        if line.startswith("data: "):
            data = line[6:]
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                print("Could not parse JSON from SSE data:", data)
                return None
    return None