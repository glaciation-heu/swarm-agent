from typing import Annotated, Any, Dict

from fastapi import Body, Query
from pydantic import BaseModel


class ResponseHead(BaseModel):
    vars: list[str]


class ResponseResults(BaseModel):
    bindings: list[Dict[str, Any]]


class SearchResponse(BaseModel):
    head: ResponseHead
    results: ResponseResults

    class Config:
        json_schema_extra = {
            "example": {
                "head": {"vars": ["sub", "pred", "obj"]},
                "results": {
                    "bindings": [
                        {
                            "sub": {
                                "type": "uri",
                                "value": "http://data.kasabi.com/dataset/cheese/halloumi",
                            },
                            "pred": {
                                "type": "uri",
                                "value": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                            },
                            "obj": {
                                "type": "uri",
                                "value": "http://data.kasabi.com/dataset/cheese/schema/Cheese",
                            },
                        },
                        {
                            "sub": {
                                "type": "uri",
                                "value": "http://data.kasabi.com/dataset/cheese/halloumi",
                            },
                            "pred": {
                                "type": "uri",
                                "value": "http://www.w3.org/2000/01/rdf-schema#label",
                            },
                            "obj": {
                                "type": "literal",
                                "xml:lang": "el",
                                "value": "Halloumi",
                            },
                        },
                    ]
                },
            }
        }


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
