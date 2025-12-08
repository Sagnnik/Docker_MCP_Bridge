import httpx
import json
from typing import Optional, List, Dict, Any
from utils import parse_sse_json

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_URL = "http://localhost:8811/mcp"

class MCPGatewayClient:
    def __init__(self):
        self.gateway_url = MCP_URL
        self.session_id:Optional[str]=None
        self._next_id = 1
        self.dynamic_tools_enabled = False
        self.code_mode_enabled = False
        self.active_servers: List[str] = []
        self.available_tools: Dict[str, Dict] = {}

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
        try:
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
        except Exception as e:
            print(f"Error connecting to MCP Gateway: {str(e)}")
    
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
        try:
            response = await client.post(
                url=self.gateway_url,
                json=payload,
                headers=headers
            )
            data = parse_sse_json(response.text)
            if "error" in data:
                raise RuntimeError(f"MCP tools/list error: {data['error']}")
            
            tools = data.get('result').get('tools')
            for tool in tools:
                self.available_tools[tool["name"]] = tool

            #print(f"Loaded {len(self.available_tools)} tools from MCP Gateway")

            if "mcp-find" in self.available_tools and 'mcp-add' in self.available_tools and 'mcp-remove' in self.available_tools:
                self.dynamic_tools_enabled = True
                #print("Docker Dynamic Tools (mcp-find, mcp-add, mcp-remove) available")

            if "code-mode" in self.available_tools:
                self.code_mode_enabled = True
                #print("Docker code-mode available")
            
            return tools
        except Exception as e:
            print(f"Error connecting to MCP Gateway: {str(e)}")
    
    async def call_tool(self, client:httpx.AsyncClient, name:str, arguments: Dict[str, Any]):
        if name not in self.available_tools:
            raise ValueError(f"Tool {name} not found")
        
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
        try:
            response = await client.post(
                url=self.gateway_url,
                json=payload,
                headers=headers
            )
            data = parse_sse_json(response.text)
            if 'error' in data:
                raise RuntimeError(f"MCP tools/call error: {data['error']}")
            
            return data["result"]
        except Exception as e:
            raise RuntimeError(f"Error calling tool {name}: {e}")
        
    async def find_mcp_servers(self,client: httpx.AsyncClient, query:str):
        if not self.dynamic_tools_enabled:
            return []
        
        try:
            result = await self.call_tool(client=client, name="mcp-find", arguments={"query": query})
            result = json.loads(result['content'][0]['text'])
            return result['servers']
        except Exception as e:
            print(f"Error finding MCP servers: {e}")
            return []

    async def add_mcp_servers(self, client: httpx.AsyncClient, server_name:str, activate:bool=True):
        if not self.dynamic_tools_enabled:
            return False
        
        try:
            result = await self.call_tool(client=client, name="mcp-add", arguments={"name": server_name, "activate": activate})
            if result.get('content'):
                if server_name not in self.active_servers:
                    self.active_servers.append(server_name)
                _ = await self.list_tools(client=client)
            return result
        
        except Exception as e:
            print(f"Error adding MCP server {server_name}: {e}")
            return False
        
    async def remove_mcp_servers(self, client: httpx.AsyncClient, server_name: str):
        # this is not working
        if not self.dynamic_tools_enabled:
            return False
        
        try:
            result = await self.call_tool(client=client, name="mcp-remove", arguments={"name": server_name})
            print(f"Remove result: {result}")  # Debug line
            
            if result.get('content'):
                if server_name in self.active_servers:
                    self.active_servers.remove(server_name)
                    print(f"Removed {server_name} from active_servers")  # Debug line
                
                tools = await self.list_tools(client=client)
                print(f"Active servers after removal: {self.active_servers}")  # Debug line
                print(f"Available tools count: {len(self.available_tools)}")  # Debug line
                
            return result
        
        except Exception as e:
            print(f"Error removing MCP server {server_name}: {e}")
            return False
        
        except Exception as e:
            print(f"Error removing MCP server {server_name}: {e}")
            return False
        
    async def create_dynamic_code_tool(self, client: httpx.AsyncClient, code: str, name: str, servers: List[str], timeout: int = 30):
        """This creates a dynamic tool"""
        if not self.code_mode_enabled:
            raise RuntimeError("Code mode not available in gateway")
        if not servers or len(servers) == 0:
            raise ValueError("At least one server must be provided for code-mode")
        
        arguments = {
            "code": code,
            "name": name,
            "servers": servers,  
            "timeout": timeout
        }
        
        try:
            result = await self.call_tool(
                client=client, 
                name='code-mode', 
                arguments=arguments
            )
            tool_name = f"code-mode-{name}"
            
            return {
                "tool_name": tool_name,
                "raw_result": result
            }
        except Exception as e:
            raise RuntimeError(f"Error executing code-mode: {e}")
        
    async def execute_dynamic_code_tool(self, client: httpx.AsyncClient, tool_name: str, script:str):
        """Execute the created tool"""
        try:
            result = await self.call_tool(
                client=client,
                name="mcp-exec",
                arguments={
                    "name": tool_name,
                    "arguments": {
                        "script": script
                    }
                }
            )
            return result
        except Exception as e:
            raise RuntimeError(f"Error executing dynamic code tool {tool_name}: {e}")