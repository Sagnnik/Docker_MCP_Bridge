from mcp_host import MCPGatewayClient
import httpx
import asyncio
import json
script = """
const fib = (n) => {
    if (n <= 1) return n;
    let a = 0, b = 1;
    for (let i = 2; i <= n; i++) {
        [a, b] = [b, a + b];
    }
    return b;
};

const sequence = [];
for (let i = 0; i < 10; i++) {
    sequence.push(fib(i));
}

return JSON.stringify({
    fibonacci_sequence: sequence,
    fib_20: fib(20)
}, null, 2);
"""

async def dynamic_mcp_test():
    mcp = MCPGatewayClient()
    async with httpx.AsyncClient(timeout=300) as client:
        await mcp.initialize(client)
        await mcp.list_tools(client)

        servers = await mcp.find_mcp_servers(client=client, query="wikipedia-mcp")
        server_name = servers[0]['name']
        print("\n=== SERVERS ===")
        print(servers)
        try:
            add_mcp_result = await mcp.add_mcp_servers(client=client, server_name=server_name)
            await asyncio.sleep(2)
            print("\n=== ADD MCP ===")
            print(add_mcp_result)

            create_result = await mcp.create_dynamic_code_tool(
                client=client,
                code='',
                name="wiki-test",
                servers=[server_name],
                timeout=30
            )   # This creates a text (.md) result of tool descriptions available in the mcp server as a reference for the LLM
            print("\n=== Create Tool Result ===")
            print(create_result)
            tool_name = create_result["tool_name"]

            result = await mcp.execute_dynamic_code_tool(
                client=client,
                tool_name=tool_name,
                script=script
            )
            
            print("\n=== RUNNING JS CODE ===")
            content_text = result['content'][0]['text']
            
            try:
                parsed = json.loads(content_text)
                print(json.dumps(parsed, indent=2))
            except:
                print(content_text)
        finally:
            await mcp.remove_mcp_servers(client=client, server_name=server_name)


if __name__ == "__main__":
    asyncio.run(dynamic_mcp_test())