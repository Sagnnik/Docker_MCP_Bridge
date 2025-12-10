### Secrets
Docker mcp secrets are managed by docker desktop secrets.  

**Note:**  
Docker MCP toolkit does't have proper support for WSL. So, if you want to set the secrets then run `docker mcp secrets set <KEY>=<VALUE>`. In the agent prompt decide to `skip` addding secrets, `mcp-add` can pick up the secrets automatically. 