from pydantic import BaseModel

class Message(BaseModel):
    unique_id: str
    sparql_query: str
    visited_nodes: list
    time_to_live: int = None
    keyword: str = ""
    