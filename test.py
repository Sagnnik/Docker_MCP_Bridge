import os
import httpx
import asyncio
import json
import copy
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from utils import parse_sse_json
from mcp_host import MCPGatewayClient
from prompts import SYSTEM_MESSAGES, LLM_TOOL_SCHEMAS

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

def extract_text_from_content(content_items: List[Dict]) -> str:
    """Extract text from MCP content items"""
    text_parts = []
    for item in content_items:
        if item.get('type') == "text" and 'text' in item:
            text_parts.append(item['text'])
    return "\n".join(text_parts) if text_parts else json.dumps(content_items)

def tool_schema_conversion(mcp_tools: List[Dict[str, Any]], mode: str='default'):
    """
    Convert MCP tool definitions to OpenAI function tools
    Now handles dynamic MCP tools (mcp-find, mcp-add, mcp-remove) and code-mode
    Modes: 
    - default: Added servers in docker compose
    - dynamic: tool search tool
    - code: LLM creates custom tool
    """    
    tools: List[Dict[str, Any]] = []

    dynamic_tools = {'mcp-find'}
    code_mode_tools = {'code-mode', 'mcp-exec'}
    exposed_tools = dynamic_tools | code_mode_tools

    def is_custom(name:str):
        return name.startswith("code-mode-") and name not in {"code-mode"}
    
    def should_expose(name:str):
        if mode == 'default':
            if name in exposed_tools:
                return False
            if is_custom(name):
                return False
            return True
        
        elif mode == 'dynamic':
            if name in code_mode_tools:
                return False
            if is_custom(name):
                return False
            return True
        elif mode == 'code':
            if name in exposed_tools:
                return True
            if is_custom(name):
                return True
            return False
        else:
            return ValueError(f"Unknown Mode: {mode}")
        

    for t in mcp_tools:
        name = t.get('name')
        if not name or not should_expose(name):
            continue

        description = t.get("description", "")
        
        # Use cleaner schemas for dynamic mcps
        if name in LLM_TOOL_SCHEMAS:
            input_schema = copy.deepcopy(LLM_TOOL_SCHEMAS[name])
        else:
            # For other tools, use original schema with fixes
            input_schema = copy.deepcopy(t.get("inputSchema", {})) or {}
            
            if input_schema.get('type') is None:
                input_schema['type'] = 'object'
            if 'properties' not in input_schema:
                input_schema['properties'] = {}
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

async def gpt_with_mcp(user_message: str, max_iterations: int=10, mode: str="default", initial_servers: List[str]=None):
    """
    GPT with MCP integration with 3 modes:
    - default: User preconfiged MCP servers only
    - dynamic: Allow LLMs to discover and add MCP servers dynamically
    - code: Enable code-mode for creating custom js/ts tools
    """
    mcp = MCPGatewayClient()

    async with httpx.AsyncClient(timeout=300) as client:
        await mcp.initialize(client)

        # Addining user specified inital servers 
        if initial_servers:
            for server in initial_servers:
                print(f"Adding initial server: {server}")
                await mcp.add_mcp_servers(client, server)

        mcp_tools = await mcp.list_tools(client)

        # Convert tools based on mode
        openai_tools = tool_schema_conversion(mcp_tools, mode=mode)

        # Debug: Print converted tools
        print(f"\n=== Converted {len(openai_tools)} tools for mode '{mode}' ===")
        for tool in openai_tools:
            print(f"  - {tool['function']['name']}")

        # Debug: Print full schema to check for issues
        if mode != "default":
            print("\n=== Full Tool Schemas (for debugging) ===")
            print(json.dumps(openai_tools, indent=2))

        messages = [
            {
                "role": "system",
                "content": SYSTEM_MESSAGES.get(mode)
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

        for iteration in range(max_iterations):
            payload = {
                "model": "gpt-5-mini",
                "messages": messages,
                "tools": openai_tools,
                "tool_choice": "auto"
            }

            response = await client.post(
                OPENAI_API_URL,
                headers=headers,
                json=payload
            )
            # Debug: Print response details if there's an error
            if response.status_code != 200:
                print(f"\n=== OpenAI API Error ===")
                print(f"Status Code: {response.status_code}")
                print(f"Response: {response.text}")
                print(f"\n=== Request Payload ===")
                print(json.dumps(payload, indent=2))
            response.raise_for_status()
            data = response.json()

            assistant_message = data['choices'][0]['message']
            finish_reason = data['choices'][0]['finish_reason']
            messages.append(assistant_message)

            if finish_reason == 'stop':
                return {
                    "content": assistant_message.get('content'),
                    "active_servers": mcp.active_servers,
                    "available_tools": list(mcp.available_tools.keys()),
                    "full_response": data
                }
            
            if finish_reason == 'tool_calls' and assistant_message.get('tool_calls'):
                tool_calls = assistant_message['tool_calls']
                print(f"\n==== Iteration {iteration+1}/{max_iterations} ==== Processing {len(tool_calls)} tool calls ====\n")
                tools_changed = False

                for tc in tool_calls:
                    tool_name = tc['function']['name']
                    tool_args = json.loads(tc['function']['arguments'])
                    tool_call_id = tc['id']

                    print(f"Calling tool: {tool_name} with args: {tool_args}")

                    try:
                        # Handle mcp-find - automatically add the first server found
                        if tool_name == "mcp-find":
                            servers = await mcp.find_mcp_servers(client, tool_args.get('query'))
                            
                            # Auto-add the first server found
                            if servers and len(servers) > 0:
                                print(f"Auto-adding first server: {servers[0]}")
                                if mode == 'dynamic':
                                    activate=True
                                if mode == 'code':
                                    activate=False
                                await mcp.add_mcp_servers(client, servers[0], activate)
                                tools_changed = True
                            
                            result_text = json.dumps({"servers": servers})
                            
                        # Handle code-mode - create a custom tool code-mode-{name}
                        elif tool_name == "code-mode":
                            result = await mcp.create_dynamic_code_tool(
                                client,
                                code='',
                                name=tool_args.get('name'),
                                servers=tool_args.get('servers'),
                                timeout=tool_args.get('timeout', 30)
                            )
                            tools_changed = True
                            result_text = json.dumps(result)

                        # Handle mcp-exec - Runs the generated script
                        elif tool_name == "mcp-exec":
                            exec_tool_name = tool_args.get('name')
                            exec_arguments = tool_args.get('arguments', {})
                            script = exec_arguments.get('script', '')
                            
                            print("\n=== Code to be Executed ===\n")
                            print(script if script else "No script provided")
                            
                            exec_result = await mcp.execute_dynamic_code_tool(
                                client,
                                tool_name=exec_tool_name,
                                script=script
                            )
                            
                            if isinstance(exec_result, dict) and 'content' in exec_result:
                                result_text = extract_text_from_content(exec_result['content'])
                            else:
                                result_text = json.dumps(exec_result)

                        else:
                            # Regular MCP tool call
                            tool_result = await mcp.call_tool(
                                client=client, 
                                name=tool_name, 
                                arguments=tool_args
                            )
                            
                            if isinstance(tool_result, dict) and 'content' in tool_result:
                                result_text = extract_text_from_content(tool_result['content'])
                            else:
                                result_text = json.dumps(tool_result)

                        print(f"\n=== Result Text after {iteration+1} ===\n")
                        print(f"Tool result preview: {result_text[:200]}...")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_text
                        })

                    except Exception as e:
                        error_msg = f"Error calling tool {tool_name}: {str(e)}"
                        print(error_msg)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": error_msg
                        })

                if tools_changed:
                    print("Tools changed, refreshing tool list...")
                    mcp_tools = await mcp.list_tools(client)
                    openai_tools = tool_schema_conversion(mcp_tools, mode=mode)
                    print(f"Now have {len(openai_tools)} tools available")
                    for tool in openai_tools:
                        print(f"  - {tool['function']['name']}")
                
                continue
            
            # Unexpected finish reason
            print(f"Unexpected finish_reason: {finish_reason}")
            break
            
        return {
            "content": "Maximum iterations reached without completion",
            "messages": messages,
            "active_servers": mcp.active_servers,
            "available_tools": list(mcp.available_tools.keys()),
            "full_response": data
        }

if __name__ == "__main__":
    async def test_default_mode():
        """Testing with pre-configed docker compose tools"""
        print("\n=== Test Default Mode ===\n")
        answer = await gpt_with_mcp(
            user_message="Who is Alan Turing? Use wikipedia-mcp and give the answer",
            max_iterations=5,
            mode='default'
        )
        print("\n=== Answer ===\n")
        print(answer['content'])
        print(f"\n Active servers: {answer['active_servers']}")

    async def test_dynamic_mode():
        """Test with dynamic server discovery and addition"""
        print("\n=== Testing Dynamic Mode ===\n")
        answer = await gpt_with_mcp(
            user_message="I need to search for information about Python programming. Find and add an appropriate MCP server, then search for Python tutorials. Ideally user wikipedia-mcp",
            max_iterations=10,
            mode="dynamic"
        )
        print("\n==== Answer ====\n")
        print(answer['content'])
        print(f"\nActive servers: {answer['active_servers']}")
        print(f"Available tools: {len(answer['available_tools'])}")

    async def test_code_mode():
        """Test with code-mode for custom tools"""
        print("\n=== Testing Code Mode ===\n")
        answer = await gpt_with_mcp(
            user_message="Create a custom tool that fetches information about multiple topics from wikipedia-mcp and combines them into a summary. Then search for deep learning and give me the final summary",
            max_iterations=10,
            mode="code",
            initial_servers=["wikipedia-mcp"]
        )
        print("\n==== Answer ====\n")
        print(answer['content'])
        print(f"\nActive servers: {answer['active_servers']}")

    # asyncio.run(test_default_mode())
    # asyncio.run(test_dynamic_mode())
    asyncio.run(test_code_mode())