from typing import Any, Dict

from io import StringIO
from json import dumps

from fastapi import APIRouter

from starlette.status import HTTP_303_SEE_OTHER
from starlette.responses import RedirectResponse

# from app.utils import get_keyword_from_query
from app.swarm_agent import SwarmAgent

router = APIRouter()

@router.get(
    "/",
    status_code=HTTP_303_SEE_OTHER,
    include_in_schema=False,
)
async def read_root() -> RedirectResponse:
    """Redirect to Swagger"""
    return RedirectResponse(url="/docs", status_code=HTTP_303_SEE_OTHER)

@router.get(
    "/api/v0/graph",
)
async def receive_query(
    query: str,
) -> str:
    """Get a query and create a keyword out of it!"""
    
    # keyword = get_keyword_from_query(query)
    swarm_agent = SwarmAgent(query, "app/parameters.json")
    
    return swarm_agent.keyword
    
        