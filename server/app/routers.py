from queue import Queue
from threading import Thread
from time import time

from fastapi import APIRouter, HTTPException
from loguru import logger
from starlette.responses import RedirectResponse
from starlette.status import (
    HTTP_303_SEE_OTHER,
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from app.consts import MY_NODE_NAME, MY_POD_NAME
from app.schemas import Message, PheromoneRequestBody, SearchResponse
from app.swarm_agent import SwarmAgent
from app.utils import local_query

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

    return f"Success - processed by pod '{MY_POD_NAME}' on node '{MY_NODE_NAME}'."


@router.post(
    "/api/v0/pheromone",
)
async def pheromone_pointing_to_neighbor(
    body: PheromoneRequestBody,
) -> SearchResponse:
    if "neighbor" not in body:
        msg = (
            "The structure of the request body should be: "
            '{"neighbor": <neighbor-pod-name>}'
        )
        logger.error(msg)
        raise HTTPException(HTTP_400_BAD_REQUEST, msg)

    pod_name = MY_POD_NAME
    pheromone_query = f"""
    SELECT ?keyword ?pheromone_value
    WHERE {{
        GRAPH <swarm-agent:pheromones> {{
            <swarm:{pod_name}> <swarm:hasAssociation> ?assoc .
            ?assoc <swarm:hasKeyword> ?keyword ;
                    <swarm:hasNeighbor> <{body['neighbor']}> ;
                    <swarm:hasPheromoneValue> ?pheromone_value .
        }}
    }}"""

    logger.info(
        f"Finding pheromones pointing from \"{pod_name}\" to \"{body['neighbor']}\"."
    )

    try:
        return local_query(pheromone_query)
    except Exception as e:
        logger.exception("An error occured")
        raise HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR,
            str(e),
        )


def swarm_agent_control():
    while True:
        message = queue.get()

        try:
            swarm_agent = SwarmAgent(message, "app/parameters.json")

            is_backward_ant_done, results = swarm_agent.step()

            if is_backward_ant_done:
                logger.info(
                    "A Backward Ant with id '{id}' carried back "
                    "a response for query '{query}'.",
                    id=swarm_agent.unique_id,
                    query=swarm_agent.query,
                )
                logger.info(f"Results:\n{results.model_dump_json(indent=2)}")
        except Exception:
            logger.exception("An error occurred")


swarm_agent_control_thread = Thread(target=swarm_agent_control, daemon=True)
swarm_agent_control_thread.start()

# TODO aggregate the results carried back by backward ants
