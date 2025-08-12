from typing import Any, Literal

import time
from os import environ

import requests
from kubernetes import client, config
from loguru import logger
from requests.exceptions import ConnectionError, Timeout

from app.consts import (
    METADATA_SERVICE_IP,
    METADATA_SERVICE_PORT,
    MY_NODE_NAME,
    MY_POD_NAMESPACE,
)
from app.schemas import EMPTY_SEARCH_RESPONSE, SearchResponse


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
) -> requests.Response:
    """
    Make a request with retries and exponential backoff.

    :param url: The URL to make the request to.
    :param max_retries: The maximum number of retry attempts.
    :param backoff_factor: The factor by which the delay increases between retries.
    :param request_type: The type of the request (can be get or post).
    :return: The response object if the request is successful.
    :raises: requests.exceptions.RequestException if all retries fail.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            if request_type == "get":
                response = requests.get(url, params=params, timeout=10)
            else:
                response = requests.post(url, json=params, timeout=10)
            response.raise_for_status()  # Raise an exception for HTTP errors
            logger.info(f"Request to {url} succeeded on attempt {attempt + 1}")
            return response
        except (ConnectionError, Timeout) as e:
            attempt += 1
            wait_time = backoff_factor * (2 ** (attempt - 1))
            logger.debug(
                "Attempt {attempt} failed: {e}. Retrying in {wait_time} seconds...",
                attempt=attempt,
                e=e,
                wait_time=wait_time,
            )
            time.sleep(wait_time)
    raise requests.exceptions.RequestException(f"All {max_retries} attempts failed.")


def local_query(query: str) -> SearchResponse:
    """
    Queries Local Metadata service
    """
    params = {"query": query}
    base_url = f"{metadata_service_url()}/api/v0/graph"

    try:
        # response = requests.get(base_url, params=params)
        response = make_request_with_retries(base_url, params)
    # except Exception as e:
    except requests.exceptions.RequestException as e:
        logger.error(str(e))
        raise e

    if response.status_code == 200:
        return SearchResponse.model_validate_json(response.text)
    else:
        logger.error(f"Error: {response.status_code}, {response.text}")

    return EMPTY_SEARCH_RESPONSE


def send_message(message, url, endpoint="api/v0/create_agent"):
    url = f"{url}/{endpoint}"

    try:
        response = make_request_with_retries(url, message, "post")
        if response.status_code != 200:
            logger.error(f"Error: {response.status_code}, {response.text}")

        return response
    except Exception as e:
        logger.exception("An error occurred")
        raise e


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
