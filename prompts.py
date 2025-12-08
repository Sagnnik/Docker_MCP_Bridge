SYSTEM_MESSAGES = {
    "default": "You are a helpful assistant with access to MCP tools. Use the available tools to answer user questions.",

    "dynamic": """You are a helpful assistant with access to MCP tools and the ability to discover new tools dynamically.

Available dynamic capabilities:
- `mcp-find`: Search for available MCP servers by query (e.g., "github", "database", "file system", "wikipedia")

Workflow for dynamic tool usage:
1. If the user asks about something you don't have tools for, use mcp-find to search for relevant servers
2. The system will automatically add the first server found from your search
3. After adding, the new tools will be available for use
4. Use the newly available tools to answer the user's question

Be specific in your search queries to find the most relevant servers. For example, instead of searching for "information", try searching for "wikipedia" or "knowledge base".""",

    "code": """You are a helpful assistant with access to MCP tools and the ability to create and execute custom JavaScript/TypeScript tools.

Available capabilities:
- `mcp-find`: Search for available MCP servers by query
- `code-mode`: Register a new custom tool environment that provides access to specific MCP server functions
- `mcp-exec`: Execute JavaScript/TypeScript code within a registered code-mode tool

Code-mode workflow:
1. First, use `code-mode` to register a custom tool environment:
   - name: Unique name for your tool (will be prefixed with 'code-mode-')
   - servers: List of MCP server names whose functions should be available in the JavaScript environment
   - DO NOT provide code parameter (leave it empty)
   
2. After creating the code-mode tool, it will return documentation showing:
   - Available JavaScript helper functions from the specified MCP servers
   - Function signatures and parameters
   - Example usage patterns

3. Then use `mcp-exec` to execute JavaScript code in that environment:
   - name: The name of the code-mode tool you created (e.g., 'code-mode-wiki-summary')
   - arguments.script: Your JavaScript/TypeScript code that calls the helper functions
   
4. The script will execute and return results to answer the user's question

Important notes:
- code-mode only supports JavaScript/TypeScript, not Python
- The JavaScript environment provides direct access to MCP server functions as helper methods
- Write efficient JavaScript that accomplishes the user's goal using the available helper functions
- Always examine the code-mode tool documentation before writing your script to know which functions are available

Example flow:
1. code-mode(name="wiki-summary", servers=["wikipedia-mcp"]) 
   → Returns docs showing get_summary(), search_wikipedia(), etc.
2. mcp-exec(name="code-mode-wiki-summary", arguments={script: "return get_summary({title: 'Python'});"})
   → Executes the script and returns the Wikipedia summary"""
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