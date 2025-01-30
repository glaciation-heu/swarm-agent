# from json import dumps
from queue import Queue
from threading import Thread

from fastapi import APIRouter
from loguru import logger
from starlette.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from app.schemas import Message

# from app.utils import get_keyword_from_query
from app.swarm_agent import SwarmAgent

# from app.schemas import (
#     ResponseHead,
#     ResponseResults,
#     SearchResponse,
#     SPARQLQuery,
#     UpdateRequestBody,
# )

router = APIRouter()
queue: Queue[Message] = Queue()


@router.get(
    "/",
    status_code=HTTP_303_SEE_OTHER,
    include_in_schema=False,
)
async def read_root() -> RedirectResponse:
    """Redirect to Swagger"""
    return RedirectResponse(url="/docs", status_code=HTTP_303_SEE_OTHER)


# @router.get(
#     "/api/v0/graph",
# )
# async def receive_query(
#     query: str,
# ) -> str:
#     """Receive query, create Swarm Agent, make a step"""

#     swarm_agent = SwarmAgent(query, "app/parameters.json")
#     response = swarm_agent.step()

#     return dumps(response.json())  # swarm_agent.keyword


@router.post(
    "/api/v0/create_agent",
)
async def receive_message(
    message: Message,
) -> str:
    """
    Receive message, parse it, create Swarm Agent, make a step.
    We can use the same function to receive messages from both
    Metadata Service and other Swarm Agents.
    """

    logger.debug("router received message {message}", message=message.model_dump())

    queue.put(message)

    # swarm_agent = SwarmAgent(message, "app/parameters.json")
    # response = await swarm_agent.step()

    # nice_str = ""
    # for binding in response["results"]["bindings"]:
    #     nice_str += str(binding) + " "

    return "Success"  # response['results']['bindings'] #swarm_agent.keyword


# TODO make sure that create_agent endpoint does not have to wait for response,
#      just creates the forward/backward agent


def swarm_agent_control():
    while True:
        message = queue.get()

        swarm_agent = SwarmAgent(message, "app/parameters.json")
        response = swarm_agent.step()

        logger.debug(f"Got response after swarm_agent.step(): {response}")


swarm_agent_control_thread = Thread(target=swarm_agent_control, daemon=True)
swarm_agent_control_thread.start()

# TODO aggregate the results carried back by backward ants
