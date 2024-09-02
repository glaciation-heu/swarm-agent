from typing import Any, Dict

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from prometheus_fastapi_instrumentator import Instrumentator

# from . import example, items
from app import routers


class CustomFastAPI(FastAPI):
    def openapi(self) -> Dict[str, Any]:
        if self.openapi_schema:
            return self.openapi_schema
        openapi_schema = get_openapi(
            title="Swarm Agent",
            version="0.2",
            description="This service implements ACO algorithm for data \
                search and movement",
            contact={
                "name": "Lakeside Labs",
                "email": "chepizhko@lakeside-labs.com",
            },
            license_info={
                "name": "MIT License",
                "url": (
                    "https://github.com/glaciation-heu" "/swarm-agent/blob/main/LICENSE"
                ),
            },
            routes=self.routes,
        )
        self.openapi_schema = openapi_schema
        return self.openapi_schema


app = CustomFastAPI()
app.include_router(routers.router)

# app.include_router(items.routes.router)

Instrumentator().instrument(app).expose(app)
