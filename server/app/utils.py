from os import environ

import requests
from kubernetes import client, config
from loguru import logger

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


def local_query(query: str) -> SearchResponse:
    """
    Queries Local Metadata service
    """
    params = {"query": query}
    base_url = f"{metadata_service_url()}/api/v0/graph"

    try:
        response = requests.get(base_url, params=params)
    except Exception as e:
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
        response = requests.post(url, json=message)
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
