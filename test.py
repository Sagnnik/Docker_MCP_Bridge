import os
import httpx
import asyncio
import json
import copy
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_URL = "http://localhost:8811/mcp"

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

            print(f"Loaded {len(self.available_tools)} tools from MCP Gateway")

            if "mcp-find" in self.available_tools and 'mcp-add' in self.available_tools and 'mcp-remove' in self.available_tools:
                self.dynamic_tools_enabled = True
                print("Docker Dynamic Tools (mcp-find, mcp-add, mcp-remove) available")

            if "code-mode" in self.available_tools:
                self.code_mode_enabled = True
                print("Docker code-mode available")
            
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

    async def add_mcp_servers(self, client: httpx.AsyncClient, server_name:str):
        if not self.dynamic_tools_enabled:
            return False
        
        try:
            result = await self.call_tool(client=client, name="mcp-add", arguments={"name": server_name})
            if result.get('content'):
                self.active_servers.append(server_name)
                _ = await self.list_tools(client=client)
            return result
        
        except Exception as e:
            print(f"Error adding MCP server {server_name}: {e}")
            return False
        
    async def remove_mcp_servers(self, client: httpx.AsyncClient, server_name:str):
        if not self.dynamic_tools_enabled:
            return False
        
        try:
            result = await self.call_tool(client=client, name="mcp-remove", arguments={"name": server_name})
            if result.get('content'):
                self.active_servers.append(server_name)
                _ = await self.list_tools(client=client)
            return result
        
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
        
        
    
def tool_schema_conversion(mcp_tools: List[Dict[str, Any]]):
    """
    Convert MCP tool definitions to OpenAI function tools.
    """
    tools: List[Dict[str, Any]] = []
    for t in mcp_tools:
        name = t.get('name')
        if not name:
            continue

        description = t.get("description", "")
        input_schema = copy.deepcopy(t.get("inputSchema", {})) or {}

        if input_schema.get('type') is None:
            input_schema['type'] = "object"
        if "properties" not in input_schema:
            input_schema["properties"] = {}
        input_schema.setdefault("additionalProperties", False)
        
        tools.append(
            {
                "type": "function",
                "function": { 
                    "name": name,
                    "description": description,
                    "parameters": input_schema,
                }
            }
        )
    return tools


async def gpt_with_mcp(user_message: str, max_iterations:int=5):
    """
    Example:
    - initialize MCP
    - list tools
    - send user + tools to gpt
    - handle a round of tool calls via mcp
    - return final assitant answer
    """
    mcp = MCPGatewayClient()
    async with httpx.AsyncClient(timeout=300) as client:
        await mcp.initialize(client)
        mcp_tools = await mcp.list_tools(client)
        openai_tools = tool_schema_conversion(mcp_tools)

        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant with access to Wikipedia via tools. Use tools when the user asks about factual topics."
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        #Set max itirations of tool calls
        for i in range(max_iterations):
            payload = {
                "model": "gpt-4o-mini",
                "messages": messages,
                "tools": openai_tools,
                "tool_choice": "auto",
            }
            response = await client.post(
                OPENAI_API_URL,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            assistant_message = data['choices'][0]['message']
            finish_reason = data['choices'][0]['finish_reason']
            messages.append(assistant_message)
            
            if finish_reason == 'stop':
                return {
                    "content": assistant_message.get('content'),
                    "full_response": data
                }
            
            if finish_reason == 'tool_calls' and assistant_message.get('tool_calls'):
                tool_calls = assistant_message['tool_calls']
                print(f"\n===== Iteration {i} ===== Processing {len(tool_calls)} tool calls====")
                for tc in tool_calls:
                    tool_name = tc['function']['name']
                    tool_args = json.loads(tc['function']['arguments'])
                    tool_call_id = tc['id']

                    #Calling tool
                    try:
                        tool_result = await mcp.call_tool(client=client, name=tool_name, arguments=tool_args)
                        if isinstance(tool_result, dict) and 'content' in tool_result:
                            content_items = tool_result['content']
                            text_parts = []
                            for item in content_items:
                                if item.get('type') == "text" and 'text' in item:
                                    text_parts.append(item['text'])

                            result_text = "\n".join(text_parts)
                        else:
                            result_text = json.dumps(tool_result)

                        print(f"Tool Result Preview: {result_text[:200]}...")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_text
                        })

                    except Exception as e:
                        print(f"Error calling tool: {tool_name}: {str(e)}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": f"Error: {str(e)}"
                        })

                    continue

            print(f"Unexpected finish_reason: {finish_reason}")
            break

        return {
            "content": "Maximum iterations reached",
            "messages": messages,
            "full_response": data
        }

if __name__ == "__main__":
    async def _test():
        answer = await gpt_with_mcp(
            user_message= "Who is Alan Turing? Use wikipedia-mcp and give me the answer", max_iterations=3
        )
        print("\n====Answer====\n")
        print(answer['messages'][-1]['content'])

    asyncio.run(_test())
