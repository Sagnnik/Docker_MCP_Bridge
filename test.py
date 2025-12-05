import httpx
import json
import asyncio

server_url = "http://localhost:8811/mcp"

def parse_sse_response(response_text: str):
    lines = response_text.split("\n")
    for line in lines:
        if line.startswith("data: "):
            data = line[6:]
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                print(f"Could not parse JSON: {data}")
    return None

async def initialize_session(client: httpx.AsyncClient):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0",
            },
        },
    }

    resp = await client.post(server_url, json=payload)
    resp.raise_for_status()
    session_id = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
    print("Initialize response headers:")
    print(dict(resp.headers))
    print("Mcp-Session-Id:", session_id) # Get this session for subsequent request

    return resp.text, session_id

async def send_initialized_notification(client: httpx.AsyncClient, session_id: str):
    payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }

    resp = await client.post(
        server_url,
        json=payload,
        headers={"Mcp-Session-Id": session_id}, # Adding the session id as a header
    )
    resp.raise_for_status()
    return resp.text

async def get_tools_list(client: httpx.AsyncClient, session_id: str):
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }

    resp = await client.post(
        server_url,
        json=payload,
        headers={"Mcp-Session-Id": session_id}, # Adding the session id as a header
    )
    resp.raise_for_status()
    return resp.text

async def main():
    try:
        async with httpx.AsyncClient(
            timeout=300,
            headers={
                # Need this headers
                "Mcp-Protocol-Version": "2024-11-05",
                "Accept": "application/json, text/event-stream",
            },
            limits=httpx.Limits(max_keepalive_connections=1, max_connections=1),
        ) as client:
            print("Initializing session...")
            init_response, session_id = await initialize_session(client)
            print("Initialization response:")
            print(init_response)

            init_data = parse_sse_response(init_response)
            if init_data and "result" in init_data:
                print("\n===PARSED INITIALIZATION===")
                print(json.dumps(init_data["result"], indent=2))

            print("\nSending initialized notification...")
            notif_response = await send_initialized_notification(client, session_id)
            print("Notification response:")
            # repr prints all the characters like '\n' etc. Here the response will usually be '' since notification jRPC does not have a response
            print(repr(notif_response))

            print("\nGetting tools list...")
            tools_response = await get_tools_list(client, session_id)
            print("Tools list raw response:")
            print(tools_response)

            tools_data = parse_sse_response(tools_response)
            if tools_data:
                print("\n===PARSED TOOLS LIST===")
                print(json.dumps(tools_data, indent=2))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
