from typing import Annotated, Any, Dict, List, Literal

from fastapi import Body, Query
from pydantic import BaseModel


class ResponseHead(BaseModel):
    vars: list[str]


class ResponseResults(BaseModel):
    bindings: list[Dict[str, Any]]


class SearchResponse(BaseModel):
    head: ResponseHead
    results: ResponseResults


EMPTY_SEARCH_RESPONSE = SearchResponse(
    head=ResponseHead(vars=[]),
    results=ResponseResults(bindings=[]),
)


class Message(BaseModel):
    message_type: Literal["forward", "backward"] = "forward"
    unique_id: str = ""
    sparql_query: str = "SELECT * WHERE {?s ?p ?o} LIMIT 10"
    visited_nodes: List[dict[str, str]] = []
    link_costs: dict[str, float] = {}
    time_to_live: int = 25
    keyword: str = ""
    results: SearchResponse = EMPTY_SEARCH_RESPONSE
    time_sent: float = 0.0
    time_received: float = 0.0


UpdateRequestBody = Annotated[
    dict[str, Any],
    Body(
        description=(
            "Request body must be in JSON-LD format. "
            "It must be compatible with GLACIATION metadata upper ontology."
        ),
    ),
]

SPARQLQuery = Annotated[
    str,
    Query(
        description=(
            "SELECT query in SPARQL language. "
            "It must be compatible with GLACIATION metadata upper ontology."
        ),
    ),
]
