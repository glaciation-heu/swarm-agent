from typing import List

from concurrent.futures import ThreadPoolExecutor
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

from app.consts import MY_NODE_NAME, MY_POD_NAME, QUERY_DATA_CATALOG
from app.data_movement import get_recent_recommendations
from app.metrics import (
    ant_path_hops,
    backward_ants_total,
    forward_ants_total,
    query_hits_total,
    query_latency_seconds,
    queue_depth,
)
from app.schemas import (
    DataCatalogEntry,
    DataMovementRecommendation,
    Message,
    PheromoneRequestBody,
    SearchResponse,
)
from app.swarm_agent import SwarmAgent
from app.utils import local_query, metadata_service_url, send_message

router = APIRouter()
queue: Queue[Message] = Queue()

# Thread pool for processing incoming ant messages concurrently.
# Each worker runs a full SwarmAgent.step() — multiple ants can progress in
# parallel so a slow HTTP call in one ant doesn't stall all the others.
_process_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ant-worker")


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

    if message.message_type == "forward":
        forward_ants_total.inc()
    else:
        backward_ants_total.inc()

    queue.put(message)
    queue_depth.inc()

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
                    <swarm:hasNeighbor> "{body['neighbor']}" ;
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


def _process_message(message: Message) -> None:
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
            kw = swarm_agent.keyword
            query_hits_total.labels(keyword=kw).inc()
            ant_path_hops.labels(keyword=kw).observe(len(swarm_agent.visited_nodes))
            if swarm_agent.link_costs:
                query_latency_seconds.labels(keyword=kw).observe(
                    sum(swarm_agent.link_costs.values())
                )
    except Exception:
        logger.exception("An error occurred")
    finally:
        queue_depth.dec()


def swarm_agent_control():
    while True:
        message = queue.get()
        _process_executor.submit(_process_message, message)


swarm_agent_control_thread = Thread(target=swarm_agent_control, daemon=True)
swarm_agent_control_thread.start()

# TODO aggregate the results carried back by backward ants


@router.get(
    "/api/v0/data_movement/recommendations",
    response_model=List[DataMovementRecommendation],
)
async def data_movement_recommendations() -> List[DataMovementRecommendation]:
    """
    Returns the most recent data movement recommendations issued by this node's
    DataMovementAgent. Recommendations are advisory: they identify which neighbor
    should receive a given keyword's data based on pheromone gradients, but no
    data is moved autonomously. An operator or CRD controller should act on these.
    """
    return get_recent_recommendations()


@router.get(
    "/api/v0/data_catalog",
    response_model=List[DataCatalogEntry],
)
async def data_catalog() -> List[DataCatalogEntry]:
    """
    Returns the data placement catalog written by the hub agent at setup time.
    Each entry contains the dataset URI, the pod name that holds it, and a
    ready-to-use SPARQL query the experiment script should send as a forward ant.
    Useful for generating diverse multi-keyword workloads and for computing the
    oracle (shortest path from any query-origin node to the data-holding node).
    """
    results = local_query(QUERY_DATA_CATALOG)
    entries = []
    for result in results.results.bindings:
        dataset_uri = result["dataset"]["value"]
        located_at = result["located_at"]["value"]
        query = (
            f"SELECT ?swarmNode WHERE {{\n"
            f"    GRAPH <swarm-agent:neighbors> {{\n"
            f"        ?swarmNode <swarm:hasKnowledgeOf> <{dataset_uri}> .\n"
            f"    }}\n"
            f"}}"
        )
        entries.append(
            DataCatalogEntry(
                dataset_uri=dataset_uri,
                located_at=located_at,
                sparql_query=query,
            )
        )
    return entries


@router.post(
    "/api/v0/admin/reset_pheromones",
    status_code=200,
)
async def reset_pheromones() -> str:
    """
    Clears the local pheromone graph on this node's metadata service.
    Used by experiment scripts to simulate a mid-run topology or data-locality
    shift without restarting the pod (dynamic workload experiments).
    """
    try:
        send_message(
            {"query": "CLEAR SILENT GRAPH <swarm-agent:pheromones>"},
            metadata_service_url(),
            "api/v0/graph/update",
        )
        logger.info("Pheromone graph cleared via admin endpoint.")
        return f"Pheromone graph cleared on pod '{MY_POD_NAME}'."
    except Exception as e:
        logger.exception("Failed to clear pheromone graph")
        raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, str(e))
