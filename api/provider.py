from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from typing import Dict, List, Optional, Any
import os
import httpx
import json
from prompts import LLM_TOOL_SCHEMAS
from dotenv import load_dotenv
load_dotenv()
    
def should_expose(name:str, mode:str):
    exposed_tools = {"mcp-find", "code-mode", "mcp-exec"} 
    code_mode_tools = {"code-mode", "mcp-exec"}
    not_expose = {"mcp-add", "mcp-config-set", "mcp-remove"}

    def is_custom(name:str):
        return name.startswith("code-mode-")
    
    if mode == 'default':
        if name in not_expose:
            return False
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
        raise ValueError(f"Unknown Mode: {mode}")

class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: List[Dict], model:str, tools: Optional[List[Dict]]):
        pass

    @abstractmethod
    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='default'):
        pass

    # @abstractmethod
    # def extract_tool_calls(self, response: Dict)-> Dict:
    #     pass
    
class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str = None):
        #self.base_url = "https://api.openai.com/v1/chat/completions"
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Please set it in your environment.")

    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='dynamic'):
        """
        Convert MCP tool definitions to OpenAI function tools
        Now handles dynamic MCP tools (mcp-find, mcp-add, mcp-remove) and code-mode
        Modes: 
        - default: Added servers in docker compose
        - dynamic: tool search tool
        - code: LLM creates custom tool
        """ 
        tools: List[Dict[str, Any]] = []
        for t in mcp_tools:
            name = t.get('name')
            if not name or not should_expose(name, mode):
                continue

            description = t.get("description", "")
            # Use cleaner schemas for dynamic mcps
            if name in LLM_TOOL_SCHEMAS:
                input_schema = LLM_TOOL_SCHEMAS[name]
            else:
                # For other tools, use original schema with fixes
                input_schema = t.get("inputSchema", {})
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
    
    async def chat(
        self, 
        messages: List[Dict], 
        model: str, 
        tools: Optional[List[Dict]], 
        mode: str = "dynamic"
    ):
        client = AsyncOpenAI(
            api_key=self.api_key,
            #base_url=self.base_url,
            timeout=120.0
        )
        kwargs = {
            "model": model,
            "messages": messages
        }

        if tools:
            kwargs['tools'] = self.format_tool_for_provider(tools, mode)
            kwargs['tool_choice'] = "auto"
        
        response = await client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        assistant_message = choice.message.model_dump()
        finish_reason = choice.finish_reason
        data = response.model_dump()
        return data, assistant_message, finish_reason
    
class LLMProviderFactory:
    _providers: Dict[str, LLMProvider] = {}

    @classmethod
    def initialize_provider(cls):
        cls._providers = {
            "openai": OpenAIProvider(),
        }

    @classmethod
    def get_provider(cls, provider_name: str) -> LLMProvider:
        if not cls._providers:
            cls.initialize_provider()
        
        if provider_name not in cls._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        return cls._providers[provider_name]

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key:str = None, site_url:str = None, app_name:str = None):
        self.base_url = "https://openrouter.ai/api/v1"
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Please set it in you environment file")
        
        self.site_url = site_url or os.getenv('OPENROUTER_SITE_URL', '')
        self.app_name = app_name or os.getenv('OPENROUTER_APP_NAME', 'Docker-MCP-Bridge')

    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='dynamic'):
        """
        Convert MCP tool definitions to OpenAI-compatible function tools
        
        Note: OpenRouter passes tools through to the underlying provider.
        Tool support varies by model:
        - OpenAI models: Full support
        - Anthropic models: Full support (converted automatically)
        - Google models: Limited support
        - Some models: No tool support
        
        Modes: 
        - default: Added servers in docker compose
        - dynamic: tool search tool
        - code: LLM creates custom tool
        """ 
        tools: List[Dict[str, Any]] = []
        for t in mcp_tools:
            name = t.get('name')
            if not name or not should_expose(name, mode):
                continue

            description = t.get("description", "")
            # Use cleaner schemas for dynamic mcps
            if name in LLM_TOOL_SCHEMAS:
                input_schema = LLM_TOOL_SCHEMAS[name]
            else:
                # For other tools, use original schema with fixes
                input_schema = t.get("inputSchema", {})
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
    
    async def chat(
            self, 
            messages: List[Dict],
            model:str, 
            tools: Optional[List[Dict]],
            mode:str = "dynamic",
            provider_preferences: Optional[List[str]] = None,
            use_fallback: bool = True
    ):
        default_headers = {}
        if self.site_url:
            default_headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            default_headers["X-Title"] = self.app_name

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url= self.base_url,
            timeout=120.0,
            default_headers=default_headers
        )

        kwargs = {
            "model": model,
            "messages": messages
        }

        if tools:
            kwargs['tools'] = self.format_tool_for_provider(tools, mode)
            kwargs['tool_choice'] = "auto"

        extra_body = {}

        # Provider routing preferences
        if provider_preferences:
            extra_body['provider'] = {"order": provider_preferences}
        # Enable fallback to other providers if primary fails
        if use_fallback:
            extra_body['provider'] = extra_body.get("provider", {})
            extra_body['provider']['allow_fallbacks'] = True

        if len(messages)>50:
            extra_body['transforms'] = ["middle-out"]

        if extra_body:
            kwargs['extra_body'] = extra_body

        try:
            response = await client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            assistant_message = choice.message.model_dump()
            finish_reason = choice.finish_reason
            data = response.model_dump()
            
            return data, assistant_message, finish_reason
        except Exception as e:
            if "tool" in str(e).lower() and tools:
                # Retry without tools if tool-related error
                print(f"Tool error detected, retrying without tools: {e}")
                kwargs.pop('tools', None)
                kwargs.pop('tool_choice', None)
                response = await client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                assistant_message = choice.message.model_dump()
                finish_reason = choice.finish_reason
                data = response.model_dump()
                return data, assistant_message, finish_reason
            else:
                raise
        

