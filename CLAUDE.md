
# Project managed by LLM Middleware Runtime

This project uses `llm-mw` as a persistent context layer. Available commands:
- `llm-mw status --project LLM.Middleware.Conxtex.Framework` — show sync state
- `llm-mw memory get <domain> [key]` — read project memory
- `llm-mw skill list` — list available skills
- `llm-mw dispatch '<request>' --project LLM.Middleware.Conxtex.Framework` — auto-select skills & build delegate tasks
