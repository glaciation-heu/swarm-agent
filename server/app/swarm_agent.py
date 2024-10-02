from typing import Any, Dict

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from kubernetes import client, config
from rdflib.plugins.sparql.parser import parseQuery

from app.schemas import Message

# from app.schemas import (
#     ResponseHead,
#     ResponseResults,
#     SearchResponse,
#     SPARQLQuery,
#     UpdateRequestBody,
# )


class SwarmAgent:
    def __init__(self, message: Message, parameters_file: str):
        """
        The function initializes an object with a query, parameters loaded from a file
        and a keyword is derived from the query.

        :param query: The `query` parameter is a string that represents the search query
        in SPARQL language
        :type query: str
        :param parameters_file: The `parameters_file` is a file containing the
        parameters needed for the query. When the `__init__` method is called, the
        `load_parameters` method is used to load these parameters from the specified
        file. File is in json format which is basically a dictionary
        :type parameters_file: str
        """
        self.query = message.sparql_query
        self.parameters = self.load_parameters(parameters_file)
        self.keyword = (
            self.transform_query_to_keyword(self.query)
            if message.keyword == ""
            else message.keyword
        )
        self.visited_nodes = message.visited_nodes
        self.pheromone_table: Dict[str, Any] = {}
        now_utc = datetime.now(timezone.utc)
        self.unique_id = (
            now_utc.strftime("%Y-%m-%d %H:%M:%S.%f")
            if message.unique_id == ""
            else message.unique_id
        )
        self.time_to_live = message.time_to_live  # self.parameters["ttl"]
        self.neighbors = self.get_swarm_agent_pods()

    def load_parameters(self, file_path: str) -> Any:
        """
        The `load_parameters` function reads and loads parameters from a JSON file into
        a dictionary.

        :param file_path: The `load_parameters` function takes a file path as input and
        reads the contents of the file using the `json.load` method. It then returns the
        loaded data as a dictionary
        :type file_path: str
        :return: The `load_parameters` method is returning a dictionary containing the
        parameters loaded from the JSON file specified by the `file_path` argument.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")
        with open(file_path, "r") as file:
            return json.load(file)

    def transform_query_to_keyword(self, query):
        """
        The function `transform_query_to_keyword` extracts keywords from a query string.

        :param query: the function `transform_query_to_keyword` is designed to extract
        specific parts from a query string and transform them into a keyword. The
        function uses regular expressions to find text within curly braces `{}` in the
        query string, then processes and concatenates certain parts of the extracted
        text to form the
        :return: The function `transform_query_to_keyword` returns a keyword based on
        the input query. The keyword is generated by extracting specific parts of the
        query and combining them in a certain way.
        """

        pattern = r"\{([^}]*)\}"

        matches = re.findall(pattern, query)

        match_arr = matches[0].replace("\n", "").replace(".", "").split(" ")
        match_clean_arr = [s for s in match_arr if s]
        raw_sub, raw_pre, raw_obj = match_clean_arr

        sub = raw_sub if raw_sub[0] != "?" else ""

        pre = re.sub(r"[<>]", "", raw_pre).split("/")[-1] if raw_pre[0] != "?" else ""

        obj = raw_obj.split("^^")[0].replace('"', "") if raw_obj[0] != "?" else ""

        keyword = "_".join(filter(None, [sub, pre, obj]))
        if keyword == "":
            keyword = "all"

        return keyword

    def get_swarm_agent_pods(self):
        """
        The function `get_swarm_agent_pods` retrieves information about Swarm agent pods
        in a Kubernetes cluster.
        :return: The `get_swarm_agent_pods` function returns a list of dictionaries
        containing information about the Swarm agent pods in the Kubernetes cluster.
        Each dictionary in the list includes the name and IP address of a Swarm agent
        pod, excluding the pod with the IP address matching the value of the `MY_POD_IP`
        environment variable.
        """
        config.load_incluster_config()
        v1 = client.CoreV1Api()

        label_selector = "app.kubernetes.io/name=swarm-agent"

        pods = v1.list_namespaced_pod(
            os.environ["MY_POD_NAMESPACE"], label_selector=label_selector
        )

        swarm_agents = []
        for pod in pods.items:
            if pod.status.pod_ip != os.environ["MY_POD_IP"]:
                swarm_agents.append(
                    {
                        "name": pod.metadata.name,
                        "ip": pod.status.pod_ip,
                    }
                )

        return swarm_agents

    def get_triples_from_query(self, sparql_query):
        parsed_query = parseQuery(sparql_query)
        triple_pattern = parsed_query[1]["where"]["part"][0]["triples"][0]
        predicate = triple_pattern[1]["part"][0]["part"][0]["part"]
        local_predicate = predicate.split("/")[-1]

        local_object = str(triple_pattern[2]["string"])

        return local_predicate, local_object

    def local_query(self, query: str | None = None) -> Any:
        """
        Queries Local Metadata service
        """
        if query is None:
            query = self.query

        params = {"query": query}
        encoded_query = urlencode(params)
        base_url = "http://metadata-service:80/api/v0/graph"
        full_url = f"{base_url}?{encoded_query}"

        response = requests.get(full_url)

        return response.json()

    def get_neighbor_pheromones(self):
        """_summary_
        Reads pheromone table from a MongoDB database to appropriate variable
        """
        pheromone_query = (
            "SELECT ?keyword ?neighbor_id ?pheromone_value WHERE {"
            "GRAPH <swarm-agent:pheromones> {"
            "?entry <swarm-agent:hasKeyword> ?keyword ."
            "?entry <swarm-agent:hasNode> ?neighbor_id ."
            "?entry <swarm-agent:hasPheromone> ?pheromone_value ."
            "}"
            "}"
        )

        results = self.local_query(pheromone_query)
        for result in results["results"]["bindings"]:
            try:
                self.pheromone_table[result["keyword"]["value"]][
                    result["neighbor_id"]["value"]
                ] = float(result["pheromone_value"]["value"])
            except KeyError:
                self.pheromone_table[result["keyword"]["value"]] = {
                    result["neighbor_id"]["value"]: float(
                        result["pheromone_value"]["value"]
                    )
                }

    def getGoodnessValues(self, keyword):
        goodness_values = []

        for neighbor in self.pheromone_table[keyword]:
            goodness_values.append(
                self.pheromone_table[keyword][neighbor] * self.parameters["beta"]
            )

        return goodness_values

    def form_backward_ant_message(self):
        backward_message = ""
        return backward_message

    def create_forward_message(self) -> Message:
        message = Message(
            message_type="forward",
            unique_id="my_unique_id",
            sparql_query=self.query,
            visited_nodes=self.visited_nodes,
            time_to_live=self.time_to_live - 1,
            keyword=self.keyword,
        )
        print("from create ", message.message_type, flush=True)
        return message

    def send_message(self, message, ip, port=80, endpoint="api/v0/swarm_agent"):
        headers = {"Content-Type": "application/json", "accept": "application/json"}
        url = f"http://{ip}:{port}/{endpoint}"
        requests.post(url, json=message, headers=headers)

    def step(self):
        this_node = (
            "node1"  # one should get the actual node id from the MongoDB database
        )
        self.visited_nodes.append(this_node)
        response = self.local_query()
        self.get_neighbor_pheromones()
        print(
            "pheromone_table[{keyword}]".format(keyword=self.keyword),
            self.pheromone_table[self.keyword],
        )
        goodness_values = self.getGoodnessValues(self.keyword)
        # here we will implement first explore strategy and then the choice between
        # strategies.
        print(goodness_values)

        forward_message = self.create_forward_message()
        print("forward_message =", forward_message.model_dump_json())

        if (
            forward_message.time_to_live is not None
            and forward_message.time_to_live > 0
        ):
            self.send_message(
                forward_message.model_dump_json(), self.neighbors[0]["ip"]
            )

        # we need to modify the message
        # update visited nodes list!

        # if request fulfilled create a backward ant message

        # once proper node is chosen we need to send the message further

        return response
