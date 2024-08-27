from typing import List

from pydantic import BaseModel


class Message(BaseModel):
    message_type: str
    unique_id: str
    sparql_query: str
    visited_nodes: List[str]
    time_to_live: int | None = None
    keyword: str = ""
