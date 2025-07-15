from typing import Literal

import json
from os import environ

import requests
from kubernetes import client, config
from loguru import logger

from app.consts import MY_POD_NAMESPACE, QUERY_NEIGHBORS
from app.schemas import SearchResponse
from app.utils import metadata_service_url


def send_request(
    data: dict[str, str], method: Literal["get", "post"], endpoint: str
) -> requests.Response | None:
    url = f"{metadata_service_url()}/{endpoint}"

    response = None

    try:
        if method == "get":
            response = requests.get(url, params=data)
        else:
            response = requests.post(url, json=data)

        if response.status_code != 200:
            logger.error(f"Error: {response.status_code}, {response.text}")
    except Exception as e:
        logger.error(str(e))

    return response


def new_pods_are_same(new_pods):
    response = send_request({"query": QUERY_NEIGHBORS}, "get", "api/v0/graph")

    if response is not None and response.status_code == 200:
        results = SearchResponse.model_validate_json(response.text)
        old_pods = [result["pod"]["value"] for result in results.results.bindings]
    else:
        old_pods = []

    if len(old_pods) != len(new_pods):
        return False

    for pod in new_pods:
        if pod not in old_pods:
            return False

    return True


def generate_neighborhood(swarm_pods, kind="hub"):
    # Create a dictionary to store the neighbors
    neighbors_dict = {}

    if kind=="hub":
        # Assuming the first pod is the hub
        hub = swarm_pods[0]

        # Organize the neighbors
        for pod in swarm_pods:
            if pod == hub:
                # Hub is connected to all other nodes
                neighbors_dict[pod] = [p for p in swarm_pods if p != hub]
            else:
                # Other nodes are connected only to the hub
                neighbors_dict[pod] = [hub]

        # Convert the dictionary to a JSON string
        neighbors_json = json.dumps(neighbors_dict, indent=2)
        logger.info(f"Neighbors JSON:\n{neighbors_json}")
    elif kind=="hierarchical":
        pass
    else:
        print("Network kind not recognized!")

    return neighbors_dict


def create_neighbors():
    # Load kube config
    if "KUBERNETES_SERVICE_HOST" in environ:
        config.load_incluster_config()
    else:
        logger.error("Not running in a Kubernetes cluster.")
        return

    # Initialize the API client
    v1 = client.CoreV1Api()

    # List swarm agent pods in their namespace
    label_selector = "app.kubernetes.io/name=swarm-agent"
    pods = v1.list_namespaced_pod(MY_POD_NAMESPACE, label_selector=label_selector)

    swarm_pods = [f"{pod.metadata.name}:{pod.status.pod_ip}" for pod in pods.items]

    if new_pods_are_same(swarm_pods):
        logger.info("There is no need to update the neighborhood.")
        return

    logger.info("Updating neighborhood...")

    neighbors_dict = generate_neighborhood(swarm_pods)

    # Generate SPARQL queries
    triples = ""
    for node, neighbors in neighbors_dict.items():
        for neighbor in neighbors:
            triples += (
                "\n\t\t" if len(triples) > 0 else ""
            ) + f"<{node}> <swarm:isNeighborOf> <{neighbor}> ."

    triples += "\n\t\t" + f"<{swarm_pods[1]}> <swarm:hasKnowledgeOf> <swarm:Car1> ."
    triples += "\n\t\t" + "<swarm:Car1> <swarm:hasColor> <swarm:Blue> ."

    query = f"""INSERT DATA {{
\tGRAPH <swarm-agent:neighbors> {{
\t\t{triples}
\t}}
}}"""

    logger.info("Clearing named graph <swarm-agent:neighbors>.")
    response = send_request(
        {"query": "CLEAR GRAPH <swarm-agent:neighbors>"}, "post", "api/v0/graph/update"
    )
    logger.debug(f"Response: {response}")

    logger.info("Clearing named graph <swarm-agent:pheromones>.")
    response = send_request(
        {"query": "CLEAR GRAPH <swarm-agent:pheromones>"}, "post", "api/v0/graph/update"
    )
    logger.debug(f"Response: {response}")

    logger.info("Sending new neighbor list.")
    logger.debug(f"SPARQL Query:\n{query}")
    response = send_request({"query": query}, "post", "api/v0/graph/update")
    logger.debug(f"Response: {response}")
