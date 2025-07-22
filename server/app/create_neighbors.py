from typing import Any, Dict, List, Literal

import json
import random
from os import environ

import networkx as nx
import numpy as np
import requests
from kubernetes import client, config
from loguru import logger

from app.consts import MY_POD_NAME, MY_POD_NAMESPACE, QUERY_NEIGHBORS
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
        return None

    if len(old_pods) != len(new_pods):
        return False

    for pod in new_pods:
        if pod not in old_pods:
            return False

    return True


def createHierarchicalNetwork(
    N: int, layer_distribution: List[float], mesh_probability: float | Dict[int, float]
) -> nx.Graph:
    """
    The function `createHierarchicalNetwork` creates a
    hierarchical network with specified layer
    distribution and mesh connectivity probabilities.

    :param N: The total number of nodes in the hierarchical network
    :type N: int
    :param layer_distribution: The `layer_distribution` parameter is a list of floats
    that represents
    the distribution of nodes across the layers of the hierarchical network.
    Each element in the list
    represents the proportion of nodes in that layer compared to the total
    number of nodes (N). The
    length of the list determines the number of layers in the network
    :type layer_distribution: List[float]
    :param mesh_probability: The `mesh_probability` parameter determines
    the probability of creating an
    edge between two nodes within a layer, connected to the same parent.
    It can be either a single float
    value, which will be used for all layers, or a dictionary where the keys
    represent the layer index
    and the values represent the probability for that specific layer
    :type mesh_probability: float | Dict[int, float]
    :return: a networkx graph object.
    """
    G = nx.Graph()
    N_layers = (
        np.array(layer_distribution).cumsum() * N
    )  # The final index of each layer

    # Add first layer of nodes with full mesh connectivity
    nodes_by_parent: Dict[int, List[int]] = {}

    for i in range(int(N_layers[0])):
        nodes_by_parent[i] = []
        for j in range(i + 1, int(N_layers[0])):
            G.add_edge(i, j, weight=1)

    # Add intermediate layers of nodes connected to the mesh in a tree-like manner,
    # and create connections inside the layer with specified probability
    for layer in range(1, N_layers.shape[0] - 1):
        nodes_by_parent_temp: Dict[int, List[int]] = {}
        for i in range(int(N_layers[layer - 1]), int(N_layers[layer])):
            parent_node = random.choice(list(nodes_by_parent.keys()))
            nodes_by_parent[parent_node].append(i)
            nodes_by_parent_temp[i] = []
            G.add_edge(parent_node, i, weight=1)

        for parent_node in nodes_by_parent:
            for i in range(len(nodes_by_parent[parent_node])):
                for j in range(i + 1, len(nodes_by_parent[parent_node])):
                    if isinstance(mesh_probability, float):
                        prob = mesh_probability
                    else:
                        prob = mesh_probability[layer]

                    if random.random() < prob:
                        G.add_edge(
                            nodes_by_parent[parent_node][i],
                            nodes_by_parent[parent_node][j],
                            weight=1,
                        )

        nodes_by_parent = nodes_by_parent_temp.copy()

    # Add last layer of nodes in a tree topology
    for i in range(int(N_layers[-2]), N):
        parent_node = random.choice(list(nodes_by_parent.keys()))
        G.add_edge(parent_node, i, weight=1)

    return G


def generate_neighborhood(
    swarm_pods: List[Any], kind: Literal["hub", "hierarchical"] = "hub"
) -> Dict[Any, List[Any]]:
    # Create a dictionary to store the neighbors
    neighbors_dict = {}

    if kind == "hub":
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
    elif kind == "hierarchical":
        G = createHierarchicalNetwork(len(swarm_pods), [0.1, 0.4, 0.5], 0.3)
        mapping = {i: swarm_pods[i] for i in range(len(swarm_pods))}
        G = nx.relabel_nodes(G, mapping)
        neighbors_dict = {node: list(G.neighbors(node)) for node in G.nodes()}
        logger.debug(
            f"Neighbors created for edge-fog-cloud! There are {len(swarm_pods)} nodes!"
        )
    # else:
    #     logger.error("Network kind not recognized!")

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

    same_new_pods = new_pods_are_same(swarm_pods)

    if same_new_pods is None:
        logger.error("Couldn't check if there is a need for neighborhood update.")
        return
    elif same_new_pods:
        logger.info("There is no need to update the neighborhood.")
        return

    if MY_POD_NAME in swarm_pods[0]:
        logger.debug(f"I am hub, {MY_POD_NAME}")
        logger.info("Updating neighborhood...")

        neighbors_dict = generate_neighborhood(swarm_pods, kind="hierarchical")

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
            {"query": "CLEAR GRAPH <swarm-agent:neighbors>"},
            "post",
            "api/v0/graph/update",
        )
        logger.debug(f"Response: {response}")
        if response is None or response.status_code != 200:
            logger.error("Clearing named graph <swarm-agent:neighbors> - UNSUCCESSFUL.")
            return

        logger.info("Clearing named graph <swarm-agent:pheromones>.")
        response = send_request(
            {"query": "CLEAR GRAPH <swarm-agent:pheromones>"},
            "post",
            "api/v0/graph/update",
        )
        logger.debug(f"Response: {response}")
        if response is None or response.status_code != 200:
            logger.error(
                "Clearing named graph <swarm-agent:pheromones> - UNSUCCESSFUL."
            )
            return

        logger.info("Sending new neighbor list.")
        logger.debug(f"SPARQL Query:\n{query}")
        response = send_request({"query": query}, "post", "api/v0/graph/update")
        logger.debug(f"Response: {response}")
        if response is None or response.status_code != 200:
            logger.error("Sending new neighbor list - UNSUCCESSFUL.")
            return
    else:
        logger.debug("I'm not hub")
        return
