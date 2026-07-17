import json
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from typing import Optional

from karma.core.persistence import create_project_persistence
from karma.turn_kernel import handle_turn, TurnRequest

mcp = FastMCP("KARMA Server")

class TurnInput(BaseModel):
    project: str
    request_id: str
    task: str
    content: str
    context_snapshot_id: Optional[str] = None
    skill_name: str = "external_agent"

@mcp.tool()
def karma_turn_execute(params: TurnInput) -> str:
    """Execute a single agent turn in the KARMA framework.
    Evaluates the content via falsification gate, records experience,
    updates reward, and knowledge graph."""
    persistence = create_project_persistence(params.project)
    
    request = TurnRequest(
        project=params.project,
        request_id=params.request_id,
        task=params.task,
        content=params.content,
        context_snapshot_id=params.context_snapshot_id,
        skill_name=params.skill_name,
    )
    
    result = handle_turn(persistence, request)
    return json.dumps(result.to_dict(), indent=2)

if __name__ == "__main__":
    mcp.run()
