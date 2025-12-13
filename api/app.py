from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from provider import LLMProviderFactory
from models import ChatResponse, ChatRequest, MCPServerConfig, MCPRemoveRequest, MCPFindRequest
from gateway_client import MCPGatewayAPIClient
from logger import logger
import json

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MCP Gateway API...")
    LLMProviderFactory.initialize_provider()
    yield
    logger.info("Shutting down MCP Gateway API...")

app = FastAPI(
    title="MCP Gateway Client",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "mcp-gateway-client"}

@app.post("/chat", response_model=ChatResponse, tags=['chat'])
async def chat(request: ChatRequest):
    """
    Non-streaming chat endpoint with MCP tools
    
    Example:
    ```json
    {
        "messages": [{"role": "user", "content": "What's the weather in SF?"}],
        "model": "gpt-5-mini",
        "provider": "openai",
        "mode": "dynamic",
        "initial_servers": ["weather"]
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            for server in request.inital_servers:
                logger.info(f"Adding initial server: {server}")
                await client.add_server(server)
            provider = LLMProviderFactory.get_provider(request.provider)

            tools = await client.list_tools()
            messages = [
                {
                    "role": m.role,
                    "content": m.content
                }
                for m in request.messages
            ]

            #Agentic Loop
            for iteration in range(request.max_iterations):
                logger.info(f"Iteration {iteration + 1}/{request.max_iterations}")
                response, assistant_msg, finish_reason = await provider.chat(
                    messages=messages,
                    model=request.model,
                    tools=tools,
                    mode=request.mode
                )

                messages.append(assistant_msg)

                if finish_reason == 'stop':
                    return ChatResponse(
                        content=assistant_msg.get('content', ''),
                        active_servers=client.active_servers,
                        available_tools=list(client.available_tools.keys()),
                        finish_reason=finish_reason
                    )
                
                # Handle tool calls
                if finish_reason == "tool_calls" and assistant_msg.get('tool_calls'):
                    tools_changed = False

                    for tc in assistant_msg['tool_calls']:
                        tool_name = tc['function']['name']
                        tool_args = json.loads(tc['function']['arguments'])
                        
                        logger.info(f"Calling tool: {tool_name}")

                        try:
                            if tool_name == "mcp-find":
                                result = await client.call_tool(tool_name, tool_args)
                                result_text = json.dumps(result)
                                tools_changed = True

                            elif tool_name in ['code-mode', 'mcp-exec']:
                                result = await client.call_tool(tool_name, tool_args)
                                result_text = json.dumps(result)
                                tools_changed = True

                            else:
                                result = await client.call_tool(tool_name, tool_args)

                                if isinstance(result, dict) and 'content' in result:
                                    result_text = client._parse_response(result['content'])

                                else:
                                    result_text = json.dumps(result)

                        except Exception as e:
                            result_text = f"Error: {str(e)}"
                            logger.error(f"Toll call error: {str(e)}")

                        messages.append({
                            "tool_call_id": tc['id'],
                            "role": "tool",
                            "name": tool_name,
                            "content": result_text
                        })

                    if tools_changed:
                        tools = await client.list_tools()
                        logger.info(f"Tools refreshed, now have {len(tools)} tools")

                    continue

                logger.warning(f"Unexpected finish reason: {finish_reason}")
                break

            return ChatResponse(
                content="Max Iteration reached",
                active_servers=client.active_servers,
                available_tools=list(client.available_tools.keys()),
                finish_reason="max_iteration"
            )
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/sse/chat", tags=['chat'])
async def chat_stream(request: ChatRequest):
    """
    Streaming chat endpoint using Server-Sent Events (SSE)
    
    Streams events as they happen:
    - `status`: Connection status
    - `iteration`: Current iteration number
    - `content`: Assistant message content
    - `tool_call`: Tool being called
    - `tool_result`: Tool execution result
    - `done`: Conversation complete
    - `error`: Error occurred
    """
    async def event_generator():
        try:
            async with MCPGatewayAPIClient() as client:
                for server in request.inital_servers:
                    logger.info(f"Adding initial server: {server}")
                    await client.add_server(server)

                yield f"data: {json.dumps({"type": 'status', 'message': 'Connected to MCP'})}\n\n"

                provider = LLMProviderFactory.get_provider(request.provider)
                tools = await client.list_tools()
                messages = [
                    {
                        "role": m.role,
                        "content": m.content
                    }
                    for m in request.messages
                ]

                for iteration in range(request.max_iterations):
                    yield f"data: {json.dumps({"type": 'iteration', 'number': iteration+1})}\n\n"

                    response, assistant_msg, finish_reason = await provider.chat(
                        messages=messages,
                        model=request.model,
                        tools=tools,
                        mode=request.mode
                    )

                    # Stream assistant message
                    if assistant_msg.get('content'):
                        yield f"data: {json.dumps({'type': 'content', 'data': assistant_msg['content']})}\n\n"

                    messages.append(assistant_msg)
                    if finish_reason == 'stop':
                        yield f"data: {json.dumps({'type': 'done', 'finish_reason': finish_reason})}\n\n"
                        break

                    # Handle tool calls
                    if assistant_msg.get('tool_calls'):
                        for tc in assistant_msg['tool_calls']:
                            tool_name = tc['function']['name']
                            tool_args = json.loads(tc['function']['arguments'])

                            yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'args': tool_args})}\n\n"
                            
                            try:
                                result = await client.call_tool(tool_name, tool_args)
                                
                                if isinstance(result, dict) and 'content' in result:
                                    result_text = client._parse_response(result['content'])
                                else:
                                    result_text = json.dumps(result)
                                
                                yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'result': result_text[:500]})}\n\n"
                            
                            except Exception as e:
                                result_text = f"Error: {str(e)}"
                                yield f"data: {json.dumps({'type': 'tool_error', 'tool': tool_name, 'error': result_text})}\n\n"
                            
                            messages.append({
                                "tool_call_id": tc['id'],
                                "role": "tool",
                                "name": tool_name,
                                "content": result_text
                            })

                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
        except Exception as e:
            logger.error(f"Stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/mcp/find", tags=["mcp"])
async def find_mcp_server(request: MCPFindRequest):
    """
    Discover available MCP servers using `mcp-find`.

    Example:
    ```json
    {
        "query": "github"
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            result = await client.call_tool(
                "mcp-find",
                {"query": request.query}
            )

            return {
                "status": "success",
                "query": request.query,
                "servers": result
            }

    except Exception as e:
        logger.error(f"Find MCP server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/add", tags=['mcp'])
async def add_mcp_server(config: MCPServerConfig = Body(..., media_type="application/json")):
    """
    Add an MCP server
    
    **Security Note**: Secrets cannot be set via API. Configure them externally:
    - Docker CLI: `docker mcp secret set server/key`
    - Environment variables
    - Secret manager (AWS Secrets Manager, Vault, etc.)
    
    Example:
    ```json
    {
        "name": "github",
        "activate": true,
        "config": {
            "api_version": "v3"
        }
    }
    ```
    """

    if config.secrets:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Secrets cannot be set via API for security reasons",
                "instructions": [
                    f"Run: docker mcp secret set {config.name}=<secret>",
                    "Or configure via environment variables / secrets manager"
                ]
            }
        )
    
    try:
        async with MCPGatewayAPIClient() as client:
            if config.config:
                for key, value in config.config.items():
                    await client.call_tool("mcp-config-set", {
                        "server": config.name,
                        "key": key,
                        "value": value
                    })

                logger.info(f"Set {len(config.config)} configs for {config.name}")

            result = await client.add_server(
                server_name = config.name,
                activate=config.activate
            )

            return {
                "status": "success",
                "server": config.name,
                "active_servers": client.active_servers,
                "message": "Server added. Ensure secrets are configured externally.",
                "result": result
            }
    
    except Exception as e:
        logger.error(f"Add server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/mcp/remove", tags=["mcp"])
async def remove_mcp_server(request: MCPRemoveRequest):
    """
    Remove an MCP server
    
    Example:
    ```json
    {
        "name": "github"
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            result = await client.remove_server(request.name)

            return {
                "status": "success",
                "server": request.name,
                "result": result
            }
    
    except Exception as e:
        logger.error(f"Remove server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/mcp/servers", tags=["mcp"])
async def list_servers():
    """
    List currently active MCP servers and available tools
    """
    try:
        async with MCPGatewayAPIClient() as client:
            return {
                "active_servers": client.active_servers,
                "available_tools": list(client.available_tools.keys()),
                "tool_count": len(client.available_tools)
            }
    
    except Exception as e:
        logger.error(f"List servers error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))