from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import os
import httpx
import json

class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: List[Dict], model:str, tools: Optional[List[Dict]]) -> Dict:
        pass

    @abstractmethod
    def format_tool_for_provider(self, tool: Dict) -> Dict:
        pass

    @abstractmethod
    def extract_tool_calls(self, response: Dict)-> Dict:
        pass
    
class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str = None):
        self.base_url = "https://api.openai.com/v1"
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')

    async def chat(self, messages: List[Dict], model: str, tools: Optional[List[Dict]]):
        payload = {"model": model, "input": messages}
        if tools:
            payload['tools'] = [{"type": "function", "function": t} for t in tools]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url=f"{self.base_url}/responses", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        
    def format_tool_for_provider(self, tool: Dict):
        return {
            "name": tool.get('name'),
            "description": tool.get("description", []),
            "parameters": tool.get("parameters", [])
        }
    
    def extract_tool_calls(self, response: Dict) -> List[Dict]:
        choices = response.get("choices", [])
        if not choices:
            return []
        tool_calls = choices[0].get("message", {}).get("tool_calls", [])
        return [
            {
                "id": tc.get("id"),
                "type": tc.get("type"),
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                }
            }
            for tc in tool_calls
        ]
        

        

