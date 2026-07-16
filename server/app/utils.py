from typing import Any, Literal

import time
from concurrent.futures import ThreadPoolExecutor
from os import environ

import requests
from kubernetes import client, config
from loguru import logger
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, Timeout

from app.consts import (
    METADATA_SERVICE_IP,
    METADATA_SERVICE_PORT,
    MY_NODE_NAME,
    MY_POD_NAMESPACE,
)
from app.schemas import EMPTY_SEARCH_RESPONSE, SearchResponse

# Shared session reuses TCP connections across requests to the same host.
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)

# Thread pool for fire-and-forget inter-agent POSTs.
_send_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="agent-send")


def find_metadata_service_ip():
    if "KUBERNETES_SERVICE_HOST" in environ:
        config.load_incluster_config()
    else:
        logger.error("Not running in a Kubernetes cluster.")
        return

    # Initialize the API client
    v1 = client.CoreV1Api()

    # List Metadata Service pods in their namespace
    label_selector = "app.kubernetes.io/name=metadata-service"
    pods = v1.list_namespaced_pod(MY_POD_NAMESPACE, label_selector=label_selector)

    addresses = {pod.spec.node_name: pod.status.pod_ip for pod in pods.items}

    if MY_NODE_NAME in addresses:
        return addresses[MY_NODE_NAME]
    else:
        logger.warning(f"Metadata Service could not be found on node '{MY_NODE_NAME}'.")
        return


def find_all_metadata_service_ips() -> dict[str, str]:
    """Returns {node_name: pod_ip} for every metadata-service pod in the cluster."""
    if "KUBERNETES_SERVICE_HOST" in environ:
        config.load_incluster_config()
    else:
        logger.error("Not running in a Kubernetes cluster.")
        return {}

    v1 = client.CoreV1Api()
    label_selector = "app.kubernetes.io/name=metadata-service"
    pods = v1.list_namespaced_pod(MY_POD_NAMESPACE, label_selector=label_selector)
    return {pod.spec.node_name: pod.status.pod_ip for pod in pods.items}


def metadata_service_url():
    ip = find_metadata_service_ip()

    if ip is None:
        ip = METADATA_SERVICE_IP

    url = f"http://{ip}:{METADATA_SERVICE_PORT}"
    logger.info(f"Using for Metadata Service: {url}")

    return url


def make_request_with_retries(
    url: str,
    params: dict[str, Any],
    request_type: Literal["get", "post"] = "get",
    max_retries: int = 5,
    backoff_factor: float = 1,
    timeout: tuple[float, float] = (1.0, 5.0),
) -> requests.Response:
    """
    Make a request with retries and exponential backoff.

    timeout is a (connect_timeout, read_timeout) tuple in seconds.
    Callers that need faster failure (agent-to-agent) should pass a shorter timeout.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            if request_type == "get":
                response = _session.get(url, params=params, timeout=timeout)
            else:
                response = _session.post(url, json=params, timeout=timeout)
            response.raise_for_status()
            logger.info(f"Request to {url} succeeded on attempt {attempt + 1}")
            return response
        except (ConnectionError, Timeout) as e:
            attempt += 1
            if attempt < max_retries:
                wait_time = backoff_factor * (2 ** (attempt - 1))
                logger.debug(
                    "Attempt {attempt} failed: {e}. Retrying in {wait_time} seconds...",
                    attempt=attempt,
                    e=e,
                    wait_time=wait_time,
                )
                time.sleep(wait_time)
            else:
                logger.debug(
                    "Attempt {attempt} failed: {e}. No more retries.",
                    attempt=attempt,
                    e=e,
                )
    logger.error(f"All {max_retries} attempts to {url} failed.")
    raise requests.exceptions.RequestException(f"All {max_retries} attempts failed.")


def local_query(query: str) -> SearchResponse:
    """
    Queries Local Metadata service.

    Uses longer timeouts than inter-agent calls since SPARQL queries can be complex.
    """
    params = {"query": query}
    base_url = f"{metadata_service_url()}/api/v0/graph"

    try:
        # Metadata service SPARQL queries may take longer; allow up to 15s read timeout
        response = make_request_with_retries(
            base_url, params, timeout=(2.0, 15.0), max_retries=3, backoff_factor=0.5
        )
    # except Exception as e:
    except requests.exceptions.RequestException as e:
        logger.error(str(e))
        raise e

    if response.status_code == 200:
        return SearchResponse.model_validate_json(response.text)
    else:
        logger.error(f"Error: {response.status_code}, {response.text}")

    return EMPTY_SEARCH_RESPONSE


def send_message(
    message: dict[str, Any],
    url: str,
    endpoint: str = "api/v0/create_agent",
    timeout: tuple[float, float] = (1.0, 5.0),
) -> requests.Response:
    full_url = f"{url}/{endpoint}"

    try:
        response = make_request_with_retries(
            full_url,
            message,
            "post",
            max_retries=3,
            backoff_factor=0.3,
            timeout=timeout,
        )
        if response.status_code != 200:
            logger.error(f"Error: {response.status_code}, {response.text}")

        return response
    except Exception as e:
        logger.exception("An error occurred")
        raise e


def send_message_nowait(
    message: dict[str, Any], url: str, endpoint: str = "api/v0/create_agent"
) -> None:
    """Submit a fire-and-forget inter-agent POST and return immediately.

    Uses a tighter timeout than send_message because peer agents on the K8s
    internal network should accept the message quickly (they just enqueue it).
    Errors are logged but not propagated — lost ants are acceptable in the
    swarm algorithm.
    """

    def _send() -> None:
        try:
            send_message(message, url, endpoint, timeout=(0.5, 3.0))
            # Import here to avoid a circular import at module load time.
            from app.metrics import successful_forwarding_requests_total

            successful_forwarding_requests_total.inc()
        except Exception:
            logger.exception("Background send to {}/{} failed", url, endpoint)

    _send_executor.submit(_send)


def get_swarm_agent_neighbors(this_node, this_node_ip):
    """
    The function retrieves the neighbors of a swarm agent from a graph database.
    :return: A list of dictionaries containing the name and IP address of
    neighboring swarm agents.
    """
    query = f"""SELECT ?neighbor WHERE {{
        GRAPH <swarm-agent:neighbors> {{
            <{this_node}:{this_node_ip}> <swarm:isNeighborOf> ?neighbor .
        }}
    }}"""

    results = local_query(query)

    swarm_agents = []
    for result in results.results.bindings:
        name, ip = result["neighbor"]["value"].split(":")
        swarm_agents.append({"name": name, "ip": ip})

    return swarm_agents


def get_pheromone_table(
    this_node: str, neighbors: list[dict[str, Any]]
) -> dict[str, Any]:
    logger.debug("I am reading from pheromone table...")
    pheromone_query = f"""
    SELECT ?keyword ?neighbor_id ?pheromone_value
    WHERE {{
        GRAPH <swarm-agent:pheromones> {{
            <swarm:{this_node}> <swarm:hasAssociation> ?assoc .
            ?assoc <swarm:hasKeyword> ?keyword ;
                    <swarm:hasNeighbor> ?neighbor_id ;
                    <swarm:hasPheromoneValue> ?pheromone_value .
        }}
    }}"""

    results = local_query(pheromone_query)
    pheromone_table: dict[str, Any] = {}
    neighbors_from_ph_table = []
    for result in results.results.bindings:
        logger.debug(
            "I have found keyword {keyword} for neighbor {nbr}",
            keyword=result["keyword"]["value"],
            nbr=result["neighbor_id"]["value"],
        )
        neighbors_from_ph_table.append(result["neighbor_id"]["value"])
        try:
            pheromone_table[result["keyword"]["value"]][
                result["neighbor_id"]["value"]
            ] = float(result["pheromone_value"]["value"])
        except KeyError:
            pheromone_table[result["keyword"]["value"]] = {
                result["neighbor_id"]["value"]: float(
                    result["pheromone_value"]["value"]
                )
            }

    neighbor_ids = [name["name"] for name in neighbors]
    the_same = set(neighbors_from_ph_table) == set(neighbor_ids)
    if the_same:
        logger.debug("all neighbors are in ph table")
    else:
        logger.debug("some neighbors got lost")
        logger.debug("Neighbor list {nbrs}", nbrs=neighbors)
        logger.debug("Neighbor list from ph table {nbrs}", nbrs=neighbors_from_ph_table)

    return pheromone_table
