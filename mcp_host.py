from typing import Optional, Dict, Any, List
from utils import parse_sse_json
import httpx
import os

MCP_PROTOCOL_VERSION = "2024-11-05"

class MCPGatewayClient:
    def __init__(self, gateway_url: str = None):
        self.gateway_url = gateway_url or os.getenv("MCP_GATEWAY_URL", "http://gateway:8811")
        self.session_id: Optional[str]=None
        self._next_id = 1

    async def initialize(self, client: httpx.AsyncClient):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "gpt-mcp-bridge",
                    "version": "1.0.0"
                }
            }
        }
        self._next_id+=1
        response = await client.post(
            url=self.gateway_url,
            json=payload,
            headers={
                "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        response.raise_for_status()
        self.session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        data = parse_sse_json(response.text)
        if not data:
            raise RuntimeError(f"Invalid initialize response: {response.text}")
        
        notif_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        notif_headers = {
            "Mcp-Session-Id": self.session_id,
            "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Accept": "application/json, text/event-stream",
        }
        notif_response = await client.post(
            url=self.gateway_url,
            json=notif_payload,
            headers=notif_headers
        )
        notif_response.raise_for_status()

        return data
    
    async def list_tools(self, client: httpx.AsyncClient):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
            "params": {}
        }
        self._next_id+=1
        headers = {
            "Mcp-Session-Id": self.session_id,
            "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Accept": "application/json, text/event-stream",
        }
        response = await client.post(
            url=self.gateway_url,
            json=payload,
            headers=headers
        )
        data = parse_sse_json(response.text)
        if "error" in data:
            raise RuntimeError(f"MCP tools/list error: {data['error']}")
        
        return data['result']['tools']
    
    async def call_tool(self, client:httpx.AsyncClient, name:str, arguments: Dict[str, Any]):
        payload ={
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }
        self._next_id+=1
        headers = {
            "Mcp-Session-Id": self.session_id,
            "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Accept": "application/json, text/event-stream",
        }

        response = await client.post(
            url=self.gateway_url,
            json=payload,
            headers=headers
        )
        data = parse_sse_json(response.text)
        if 'error' in data:
            raise RuntimeError(f"MCP tools/call error: {data['error']}")
        
        return data["result"]