from typing import Annotated, Any, Dict, List

from fastapi import Body, Query
from pydantic import BaseModel


class ResponseHead(BaseModel):
    vars: list[str]


class ResponseResults(BaseModel):
    bindings: list[Dict[str, Any]]


class Message(BaseModel):
    message_type: str
    unique_id: str
    sparql_query: str
    visited_nodes: List[str]
    time_to_live: int | None = None
    keyword: str = ""


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
