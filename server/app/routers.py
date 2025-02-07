# from json import dumps
from queue import Queue
from threading import Thread
from time import sleep, time

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
    message.time_received = time()
    logger.info(
        "Router received message:\n{message}",
        message=message.model_dump_json(indent=2),
    )

    queue.put(message)

    return "Success"  # response['results']['bindings'] #swarm_agent.keyword


def swarm_agent_control():
    while True:
        message = queue.get()

        swarm_agent = SwarmAgent(message, "app/parameters.json")
        is_backward_ant_done, results = swarm_agent.step()

        if is_backward_ant_done:
            logger.info(
                "A Backward Ant carried back a response for query '{query}'",
                query=swarm_agent.query,
            )
            logger.info(f"Results:\n{results.model_dump_json(indent=2)}")


def regular_pheromone_evaporation():
    swarm_agent = SwarmAgent(Message(), "app/parameters.json")
    while True:
        swarm_agent.pheromone_evaporation()
        sleep(5)


swarm_agent_control_thread = Thread(target=swarm_agent_control, daemon=True)
swarm_agent_control_thread.start()

ph_evap_thread = Thread(target=regular_pheromone_evaporation, daemon=True)
ph_evap_thread.start()

# TODO aggregate the results carried back by backward ants
