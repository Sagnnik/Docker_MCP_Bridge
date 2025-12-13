from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "gpt-5-mini"
    provider: str = "openai"
    mode: str = Field("dynamic", description="dynamic, code or default")
    inital_servers: List[str] = []
    max_iterations: int=5
    stream: bool=False

class MCPServerConfig(BaseModel):
    name: str
    activate: bool = True
    config: Optional[Dict[str, Any]] = None
    secrets: Optional[Dict[str, str]] = None

class MCPRemoveRequest(BaseModel):
    name:str

class MCPFindRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    content: str
    active_servers: List[str]
    available_tools: List[str]
    finish_reason: str