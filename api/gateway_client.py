from typing import Optional, Dict, List, Any
import httpx
import json
from logger import logger

class MCPGatewayAPIClient:
    MCP_PROTOCOL_VERSION = "2024-11-05"
    MCP_URL = "http://localhost:8811/mcp"

    def __init__(self):
        self.session_id: Optional[str] = None
        self._next_id = 1
        self.available_tools: Dict[str, Dict] = {}
        self.active_servers: List[str] = []
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=300)
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    async def initialize(self):
        """Initialize MCP session"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": self.MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-api-gateway", "version": "1.0.0"}
            }
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        response.raise_for_status()
        
        self.session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        
        await self._client.post(
            self.MCP_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        
        await self.list_tools()
        logger.info(f"MCP session initialized: {self.session_id}")

    async def list_tools(self):
        """List available MCP tools"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
            "params": {}
        }
        self._next_id += 1

        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )

        data = self._parse_response(response.text)
        tools = data.get('result', {}).get('tools', [])
        
        self.available_tools = {tool["name"]: tool for tool in tools}
        logger.info(f"Loaded {len(self.available_tools)} tools")
        return tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        """Call an MCP tool"""
        if name not in self.available_tools:
            raise ValueError(f"Tool {name} not found")
        
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments}
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        
        data = self._parse_response(response.text)
        if 'error' in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        
        return data["result"]

    async def add_server(self, server_name: str, activate: bool = True, 
                        config: Optional[Dict] = None, secrets: Optional[Dict] = None):
        """
        Add MCP server programmatically (no interactive prompts)
        
        Args:
            server_name: Server name to add
            activate: Whether to activate immediately
            config: Optional config dict (key-value pairs)
            secrets: Optional secrets dict (handled via environment or external secret manager)
        """
        if config:
            for key, value in config.items():
                await self.call_tool("mcp-config-set", {
                    "server": server_name,
                    "key": key,
                    "value": value
                })

        # Note: Secrets should be pre-configured in environment or mounted
        # Not handled here for security reasons
        # if secrets:
        #     logger.warning(f"Secrets provided for {server_name} but must be configured externally")

        result = await self.call_tool("mcp-add", {
            "name": server_name,
            "activate": activate
        })

        if server_name not in self.active_servers:
            self.active_servers.append(server_name)
        
        await self.list_tools()
        logger.info(f"Added server: {server_name}")
        return result
    
    async def remove_server(self, server_name: str):
        """Remove MCP server"""
        result = await self.call_tool("mcp-remove", {"name": server_name})
        
        if server_name in self.active_servers:
            self.active_servers.remove(server_name)
        
        await self.list_tools()
        logger.info(f"Removed server: {server_name}")
        return result
    
    def _parse_response(self, text: str) -> Dict:
        """Parse SSE response (simplified)"""
        for line in text.strip().split('\n'):
            if line.startswith('data: '):
                return json.loads(line[6:])
        return json.loads(text)