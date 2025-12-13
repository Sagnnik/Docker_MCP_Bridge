MCP_BRIDGE_MESSAGES = {
    "default": "You are a helpful assistant with access to MCP tools. Use the available tools if required to answer user questions.",

    "dynamic": """You are a helpful assistant with access to MCP tools and the ability to discover new MCP servers dynamically.

Available capability (exposed to you):
- `mcp-find`: Search for available MCP servers by query (e.g., "github", "database", "file system", "wikipedia").

Dynamic workflow (what you should do):
1. When you need a capability or provider that isn't already available, call `mcp-find` with a concise, specific query describing the provider or capability you want (for example: "openai-mcp", "wikipedia-mcp", "postgres-mcp", "github-repo-access").
2. The runtime/CLI will handle onboarding (checking for and prompting the human for any required configs or secrets) and will add the selected server(s).
3. After the runtime adds servers, the newly available server functions/tools will be placed in your context like normal MCP servers and you can use them according to their documented APIs.

Behavior rules and constraints:
- You are only allowed to call `mcp-find` in dynamic mode. Do not assume you can call other management or code-execution tools directly.
- Be specific in your search queries so the runtime can find the intended server quickly.
- Prefer existing available tools before calling `mcp-find` to discover new ones.
- When requesting discovery, include exact capability names or short targeted search tokens (e.g., 'openai-mcp', 'wikipedia-mcp', 's3-mcp') rather than generic terms like 'information'.""",

    "code": """You are a helpful assistant with access to MCP tools and the ability to create and execute custom JavaScript/TypeScript tools via code-mode and mcp-exec.

Available capabilities (exposed to you in code mode):
- `mcp-find`: Search for available MCP servers by query
- `code-mode`: Request creation of a code-mode tool environment
- `mcp-exec`: Execute JavaScript/TypeScript code inside a created code-mode environment

Code-mode workflow (how to request and use code-mode):
1. If you need server functions not currently available, call `mcp-find` to discover them first.
2. Request a `code-mode` environment by specifying:
   - `name`: a unique name (the runtime will prefix with `code-mode-`)
   - `servers`: an explicit list of server names to include (e.g., `["wikipedia-mcp", "openai-mcp"]`)
   - Do not include executable source code in the creation call — leave the code/script empty.
3. The runtime will create the environment and return documentation showing:
   - helper functions mapped from selected MCP servers,
   - function signatures and example usage.
4. Use `mcp-exec` to run your JavaScript/TypeScript code in that environment:
   - `name`: the code-mode tool name (e.g., `code-mode-wiki-summary`)
   - `arguments.script`: your JS/TS code string calling helper methods.
5. `mcp-exec` runs the script in the sandbox and returns results for you to use in answering the user's question.

Best practices:
- Inspect the returned code-mode documentation before writing scripts.
- Keep scripts short and focused; call only the helper functions you need.
- Code-mode supports JavaScript/TypeScript only.
- Use `mcp-find` first to ensure required servers are present; the runtime will add servers and make them available in your context after any necessary human prompts."""
}



LLM_TOOL_SCHEMAS = {
        'mcp-find': {
            'type': 'object',
            'required': ['query'],
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'Search query to find MCP servers by name, title, or description. Be specific (e.g., "wikipedia", "github", "filesystem") for best results.'
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Maximum number of results to return',
                    'default': 10
                }
            },
            'additionalProperties': False
        },
        'code-mode': {
            'type': 'object',
            'required': ['name', 'servers'],
            'properties': {
                'name': {
                    'type': 'string',
                    'description': "Unique identifier for your custom tool (will be prefixed with 'code-mode-'). Use descriptive names like 'wiki-summary' or 'multi-search'."
                },
                'servers': {
                    'type': 'array',
                    'description': 'List of MCP server names whose tools will be available as JavaScript helper functions in your code environment.',
                    'items': {
                        'type': 'string'
                    },
                    'minItems': 1
                },
                'timeout': {
                    'type': 'integer',
                    'description': 'Execution timeout in seconds',
                    'default': 30
                }
            },
            'additionalProperties': False
        },
        'mcp-exec': {
            'type': 'object',
            'required': ['name', 'arguments'],
            'properties': {
                'name': {
                    'type': 'string',
                    'description': "Name of the code-mode tool to execute (must start with 'code-mode-', e.g., 'code-mode-wiki-summary')"
                },
                'arguments': {
                    'type': 'object',
                    'required': ['script'],
                    'properties': {
                        'script': {
                            'type': 'string',
                            'description': 'JavaScript/TypeScript code to execute. The code has access to helper functions from the MCP servers specified when creating this tool. Use "return" to return results.'
                        }
                    },
                    'additionalProperties': False,
                    'description': 'Execution arguments containing the script to run'
                }
            },
            'additionalProperties': False
        }
    }