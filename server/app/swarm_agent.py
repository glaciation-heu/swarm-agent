from typing import Any, Dict

import json
import random
import re
from datetime import datetime, timezone
from os import getenv, path
from time import time

from loguru import logger
from rdflib.plugins.sparql.parser import parseQuery

from app.consts import (
    MY_POD_IP,
    MY_POD_NAME,
    PARAMETER_ENV_VARIABLES,
    PHEROMONE_THRESHOLD,
)
from app.schemas import EMPTY_SEARCH_RESPONSE, Message, SearchResponse
from app.utils import (
    get_pheromone_table,
    get_swarm_agent_neighbors,
    local_query,
    metadata_service_url,
    send_message,
)


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
        self.type = message.message_type
        self.latency = message.time_received - message.time_sent
        self.this_node = MY_POD_NAME
        self.this_node_ip = MY_POD_IP
        self.query = message.sparql_query
        self.results = message.results
        self.parameters = self.load_parameters(parameters_file)
        self.keyword = (
            self.transform_query_to_keyword(self.query)
            if message.keyword == ""
            else message.keyword
        )
        self.visited_nodes = message.visited_nodes
        self.link_costs = message.link_costs
        now_utc = datetime.now(timezone.utc)
        if message.unique_id == "":
            self.unique_id = now_utc.strftime("%Y-%m-%d %H:%M:%S.%f")
            logger.debug(
                f"New agent: {self.type} ant initialized with id '{self.unique_id}'."
            )
        else:
            self.unique_id = message.unique_id
        # TODO make time_to_live real time
        self.time_to_live = message.time_to_live  # self.parameters["ttl"]
        self.neighbors = get_swarm_agent_neighbors(self.this_node, self.this_node_ip)
        self.pheromone_table: Dict[str, Any] = {}

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
        if not path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")
        with open(file_path, "r") as file:
            params = json.load(file)
            for param in PARAMETER_ENV_VARIABLES:
                params[PARAMETER_ENV_VARIABLES[param]["key"]] = float(
                    getenv(param, PARAMETER_ENV_VARIABLES[param]["default"])
                )
            logger.info(f"Parameters loaded:\n{json.dumps(params, indent=2)}")
            return params

    def transform_query_to_keyword(self, query):
        """
        Transforms a SPARQL-like query into a keyword string.
        Extracts the named graph, subject, predicate, and object.

        :param query: A SPARQL query string.
        :return: A formatted keyword string.
        """

        # Extract the named graph, if present
        graph_pattern = r"GRAPH\s*<([^>]+)>\s*\{([^}]*)\}"
        matches = re.findall(graph_pattern, query, re.DOTALL)

        keywords = []

        for graph_name, graph_content in matches:
            # Clean up the extracted triples (remove newlines and extra spaces)
            graph_content = graph_content.replace("\n", " ").strip()

            # Extract triples (split by " . ")
            triples = [t.strip() for t in graph_content.split(" . ") if t]

            for triple in triples:
                parts = triple.split()
                if len(parts) < 3:
                    continue  # Skip malformed triples

                raw_sub, raw_pre, raw_obj = parts[:3]

                # Process components, remove `<` and `>` from IRIs
                sub = raw_sub if not raw_sub.startswith("?") else ""
                pre = raw_pre.strip("<>") if not raw_pre.startswith("?") else ""
                obj = (
                    raw_obj.split("^^")[0].strip("<>").replace('"', "")
                    if not raw_obj.startswith("?")
                    else ""
                )

                # Create keyword
                keyword = "_".join(filter(None, [sub, pre, obj]))

                # Prefix with graph name if present
                keyword = f"{graph_name}_{keyword}"

                keywords.append(keyword)

        return ",".join(keywords) if keywords else "all"

    def get_triples_from_query(self, sparql_query):
        parsed_query = parseQuery(sparql_query)
        triple_pattern = parsed_query[1]["where"]["part"][0]["triples"][0]
        predicate = triple_pattern[1]["part"][0]["part"][0]["part"]
        local_predicate = predicate.split("/")[-1]

        local_object = str(triple_pattern[2]["string"])

        return local_predicate, local_object

    def delete_pheromone_entry(self, local_node_id, keyword, neighbor_id):
        pheromone_delete_query = f"""
        DELETE {{
        GRAPH <swarm-agent:pheromones> {{
            <swarm:{local_node_id}> <swarm:hasAssociation> ?association .
            ?association <swarm:hasKeyword> "{keyword}" ;
                        <swarm:hasNeighbor> "{neighbor_id}" ;
                        <swarm:hasPheromoneValue> ?pheromoneValue .
            }}
        }}
        WHERE {{
        GRAPH <swarm-agent:pheromones> {{
            <swarm:{local_node_id}> <swarm:hasAssociation> ?association .
            ?association <swarm:hasKeyword> "{keyword}" ;
                        <swarm:hasNeighbor> "{neighbor_id}" ;
                        <swarm:hasPheromoneValue> ?pheromoneValue .
            }}
        }}"""

        params = {"query": pheromone_delete_query}

        response = send_message(params, metadata_service_url(), "api/v0/graph/update")

        return response, pheromone_delete_query

    def add_pheromone_entry(self, local_node_id, keyword, neighbor_id, ph_value):
        association = f"{local_node_id}:" + keyword + "---" + neighbor_id
        pheromone_insert_query = f"""INSERT DATA {{
            GRAPH <swarm-agent:pheromones> {{ <swarm:{local_node_id}>
            <swarm:hasAssociation> <{association}> .
            <{association}>
            <swarm:hasKeyword> "{keyword}" ;
            <swarm:hasNeighbor> "{neighbor_id}" ;
            <swarm:hasPheromoneValue> {ph_value} . }} }}"""

        params = {"query": pheromone_insert_query}

        response = send_message(params, metadata_service_url(), "api/v0/graph/update")

        return response, pheromone_insert_query

    def add_visitation_entry(self, local_node_id):
        clean_id = self.unique_id.replace(" ", "-").replace(":", "-")
        graph_uri = f"swarm-agent:visitation/{clean_id}"
        logger.debug(
            f"Agent {self.unique_id} | Entering add_visitation_entry for node \
                {local_node_id}"
        )

        visitation_insert_query = f"""INSERT DATA {{
                GRAPH <{graph_uri}> {{ <swarm:{local_node_id}>
                <swarm:wasVisitedBy> "{self.unique_id}" . }} }}"""

        logger.debug(f"Agent {self.unique_id} | SPARQL q.: {visitation_insert_query}")

        params = {"query": visitation_insert_query}
        try:
            response = send_message(
                params, metadata_service_url(), "api/v0/graph/update"
            )
            logger.debug(
                f"Agent {self.unique_id} | Response from metadata service: {response}"
            )

            return response, visitation_insert_query
        except Exception as e:
            logger.error(
                f"Agent {self.unique_id} \
                    | Error sending request to metadata service: {e}"
            )
            raise

    def was_node_visited_by_agent(self, local_node_id):
        logger.debug(f"Agent {self.unique_id} | checking node {local_node_id}")
        clean_id = self.unique_id.replace(" ", "-").replace(":", "-")
        graph_uri = f"swarm-agent:visitation/{clean_id}"

        ask_query = f"""
        ASK {{
            GRAPH <{graph_uri}> {{
                <swarm:{local_node_id}> <swarm:wasVisitedBy> \
                    <{self.unique_id}> .
            }}
        }}
        """

        params = {"query": ask_query}
        response = send_message(params, metadata_service_url(), "api/v0/graph/query")

        if response.status_code == 200:
            result = response.json()
            return result.get("boolean", False), ask_query
        else:
            return False, ask_query

    def update_in_two_steps(self, local_node_id, keyword, neighbor_id, ph_value):
        logger.debug("deleting old pheromone value...")
        response_delete, pheromone_delete_query = self.delete_pheromone_entry(
            local_node_id, keyword, neighbor_id
        )
        logger.debug("writing new pheromone value...")
        if ph_value > PHEROMONE_THRESHOLD:
            logger.debug(
                "ph_value LARGER than threshold: {ph_value} > {threshold}",
                ph_value=ph_value,
                threshold=PHEROMONE_THRESHOLD,
            )
            response_add, pheromone_add_query = self.add_pheromone_entry(
                local_node_id, keyword, neighbor_id, ph_value
            )
        else:
            logger.debug(
                "ph_value SMALLER than threshold: {ph_value} < {threshold}",
                ph_value=ph_value,
                threshold=PHEROMONE_THRESHOLD,
            )
            response_add, pheromone_add_query = None, None

        return (
            response_add,
            pheromone_add_query,
            response_delete,
            pheromone_delete_query,
        )

    def getGoodnessValues(self, keyword):
        goodness_values = []

        for neighbor in self.pheromone_table[keyword]:
            goodness_values.append(
                self.pheromone_table[keyword][neighbor] ** self.parameters["beta"]
            )

        return goodness_values

    def create_backward_message(
        self,
        results: SearchResponse,
        time_to_live: int | None = None,
    ) -> Message:
        message = Message(
            message_type="backward",
            unique_id=self.unique_id,
            sparql_query=self.query,
            visited_nodes=self.visited_nodes,
            link_costs=self.link_costs,
            time_to_live=(
                self.time_to_live - 1 if time_to_live is None else time_to_live
            ),
            keyword=self.keyword,
            results=results,
        )
        logger.debug("from create {message_type}", message_type=message.message_type)
        return message

    def create_forward_message(self) -> Message:
        message = Message(
            message_type="forward",
            unique_id=self.unique_id,
            sparql_query=self.query,
            visited_nodes=self.visited_nodes,
            link_costs=self.link_costs,
            time_to_live=self.time_to_live - 1,
            keyword=self.keyword,
        )
        logger.debug("from create {message_type}", message_type=message.message_type)
        return message

    def forward_ant_step(self):
        if len(self.visited_nodes) > 0:
            self.link_costs[self.this_node] = self.latency
        self.visited_nodes.append({"name": self.this_node, "ip": self.this_node_ip})
        self.add_visitation_entry(self.this_node)
        results = local_query(self.query)
        node_id = None
        for result in results.results.bindings:
            node_id = result["swarmNode"]["value"]
            node_id = node_id.split(":")[0]
        logger.debug(
            "Results found are for node: {node_id}, this node is {this_node}",
            node_id=node_id,
            this_node=self.this_node,
        )
        if node_id != self.this_node:
            results = EMPTY_SEARCH_RESPONSE

        self.pheromone_table = get_pheromone_table(self.this_node, self.neighbors)
        if self.keyword in self.pheromone_table:
            logger.debug(
                "pheromone_table[{keyword}] contains {content}",
                keyword=self.keyword,
                content=self.pheromone_table[self.keyword],
            )
        else:
            self.pheromone_table[self.keyword] = {}

            logger.debug(
                "Agent {} | I have {} neighbors", self.unique_id, len(self.neighbors)
            )
            logger.debug("Agent {} | My neighbors: {}", self.unique_id, self.neighbors)

            for neighbor in self.neighbors:
                self.pheromone_table[self.keyword][neighbor["name"]] = 0.1
                logger.debug("I am updating the pheromone table...")
                (
                    response_add,
                    pheromone_add_query,
                    response_delete,
                    pheromone_delete_query,
                ) = self.update_in_two_steps(
                    self.this_node,
                    self.keyword,
                    neighbor["name"],
                    self.pheromone_table[self.keyword][neighbor["name"]],
                )

            logger.debug(
                "Add response: {response_add}, delete response: {response_delete}",
                response_add=response_add.json(),
                response_delete=response_delete.json(),
            )

            logger.debug(
                "pheromone_table[{keyword}] = {content}",
                keyword=self.keyword,
                content=self.pheromone_table[self.keyword],
            )

        unvisited_neighbors = [
            neighbor
            for neighbor in self.getUnvisitedNeighbors()
            if not self.was_node_visited_by_agent(neighbor["name"])
        ]

        logger.debug("Agent {} | my neighbors: {}", self.unique_id, self.neighbors)
        logger.debug(
            "Agent {} | visited neighbors: {}", self.unique_id, self.visited_nodes
        )
        logger.debug(
            "Agent {} | unvisited neighbors: {}", self.unique_id, unvisited_neighbors
        )
        if len(unvisited_neighbors) > 0:
            goodness_values = self.getGoodnessValuesUnvisited(unvisited_neighbors)

            logger.debug(
                "goodness_values={goodness_values}", goodness_values=goodness_values
            )

            logger.debug(
                "self.time_to_live = {time_to_live}", time_to_live=self.time_to_live
            )

            forward_message = self.create_forward_message()

            logger.debug(
                "forward_message.time_to_live = {ttl}", ttl=forward_message.time_to_live
            )

            logger.debug("forward_message = {fm}", fm=forward_message.model_dump())

            if random.random() < self.parameters["w_exploit"]:
                # implementing exploitation
                logger.debug("Exploitation chosen!")
                chosen_nodes = self.exploit(goodness_values, unvisited_neighbors)
            else:
                # implementing exploration
                logger.debug("Exploration chosen!")
                chosen_nodes = self.explore(goodness_values, unvisited_neighbors)

                # chosen_nodes = self.exploit(goodness_values, unvisited_neighbors)
            # return the neighbors where the pheromone levels are higher
            # then the average pheromone level of the neighbors
            logger.debug("Agent {} | chosen nodes: {}", self.unique_id, chosen_nodes)
        else:
            chosen_nodes = []

        if len(chosen_nodes) > 0 and self.time_to_live > 1:
            for chosen_node in chosen_nodes:
                logger.debug(
                    "Agent {agent} | I am sending the message to \
                        {node} with IP address {node_ip}",
                    agent=self.unique_id,
                    node=chosen_node["name"],
                    node_ip=chosen_node["ip"],
                )
                forward_message.time_sent = time()
                try:
                    send_message(
                        forward_message.model_dump(),
                        f"http://{chosen_node['ip']}:80",
                    )
                    logger.debug(
                        "Agent {agent} | Successfully sent message to \
                            {node} with IP address {node_ip}",
                        agent=self.unique_id,
                        node=chosen_node["name"],
                        node_ip=chosen_node["ip"],
                    )
                except ConnectionError:
                    logger.exception(
                        "Connection error occurred while trying to send the message \
                            to {node} with IP address {node_ip}!",
                        node=chosen_node["name"],
                        node_ip=chosen_node["ip"],
                    )
        else:
            visited = "Yes!" if len(unvisited_neighbors) == 0 else "No!"
            logger.debug(
                "Agent {agent} | Ant terminated! ttl={ttl},\
                    visited all neighbors {visited}",
                agent=self.unique_id,
                ttl=self.time_to_live - 1,
                visited=visited,
            )

        if len(results.results.bindings) > 0:
            logger.debug("Agent {} | I am creating a backward ant...", self.unique_id)
            backward_message = self.create_backward_message(
                results, len(self.visited_nodes)
            )
            backward_message.time_sent = time()
            logger.debug("Sending backward message...")
            send_message(
                backward_message.model_dump(), f"http://{self.this_node_ip}:80"
            )

        # once proper node is chosen we need to send the message further

        return False, EMPTY_SEARCH_RESPONSE

    def getUnvisitedNeighbors(self):
        unvisited_neighbors = [
            neighbor
            for neighbor in self.neighbors
            if neighbor not in self.visited_nodes
        ]

        return unvisited_neighbors

    def getGoodnessValuesUnvisited(self, unvisited_neighbors):
        goodness_values = []

        for neighbor in unvisited_neighbors:
            if neighbor["name"] in self.pheromone_table[self.keyword]:
                goodness_values.append(
                    self.pheromone_table[self.keyword][neighbor["name"]]
                    ** self.parameters["beta"]
                )
            else:
                goodness_values.append(0.1 ** self.parameters["beta"])
                logger.debug(
                    "Neighbor {neighbor} not found! Minimal value ph=0.1 was used!",
                    neighbor=neighbor,
                )

        return goodness_values

    def explore(self, goodness_values, unvisited_neighbors):
        total_goodness = sum(goodness_values)
        probabilities = [value / total_goodness for value in goodness_values]
        logger.debug("probabilities: {}", probabilities)
        is_chosen = [random.random() <= prob for prob in probabilities]
        chosen_nodes = [
            neighbor for i, neighbor in enumerate(unvisited_neighbors) if is_chosen[i]
        ]
        if len(chosen_nodes) == 0:
            logger.debug(
                "No nodes chosen through probabilities. Reverting to exploitation."
            )
            chosen_nodes = self.exploit(goodness_values, unvisited_neighbors)
        return chosen_nodes

    def exploit(self, goodness_values, unvisited_neighbors):
        mean_goodness = sum(goodness_values) / len(goodness_values)
        logger.debug("mean_goodness = {}", mean_goodness)
        tolerance = 1e-5
        chosen_nodes = [
            node
            for node, goodness in zip(unvisited_neighbors, goodness_values)
            if goodness >= mean_goodness - tolerance
        ]

        return chosen_nodes

    def backward_ant_step(self):
        # hardcoded parameters for now
        w_d = 0.5
        t_max = 3
        r_max = 10

        if len(self.link_costs) > 0 and self.time_to_live < len(self.visited_nodes):
            self.pheromone_table = get_pheromone_table(self.this_node, self.neighbors)

            total_link_costs = sum(self.link_costs.values())
            z = w_d * len(self.results.results.bindings) / r_max + (
                (1 - w_d) * t_max / (2 * total_link_costs)
            )
            target_neighbor = self.visited_nodes[self.time_to_live]["name"]

            logger.debug(
                "I drop {z} amount of pheromone for neighbor {neighbor}\
                    and keyword {keyword}",
                z=z,
                neighbor=target_neighbor,
                keyword=self.keyword,
            )

            self.update_in_two_steps(
                self.this_node,
                self.keyword,
                target_neighbor,
                self.pheromone_table[self.keyword][target_neighbor] + z,
            )

        if self.time_to_live > 1:
            backward_message = self.create_backward_message(self.results)
            backward_message.time_sent = time()
            send_message(
                backward_message.model_dump(),
                f"http://{self.visited_nodes[self.time_to_live-2]['ip']}:80",
            )

            return False, EMPTY_SEARCH_RESPONSE

        return True, self.results

    def step(self):
        logger.debug("this_node = {this_node}", this_node=self.this_node)

        if self.type == "forward":
            return self.forward_ant_step()

        return self.backward_ant_step()

    def pheromone_evaporation(self):
        pheromone_table = get_pheromone_table(self.this_node, self.neighbors)

        logger.debug("I will evaporate pheromones!")
        logger.debug("The keywords are {}", list(pheromone_table.keys()))

        for keyword in pheromone_table:
            for neighbor in pheromone_table[keyword]:
                logger.debug(
                    "I evaporate {keyword} for {neighbor}. New amount: {ph_val}",
                    keyword=keyword,
                    neighbor=neighbor,
                    ph_val=pheromone_table[keyword][neighbor]
                    * (1 - self.parameters["p"]),
                )
                self.update_in_two_steps(
                    self.this_node,
                    keyword,
                    neighbor,
                    pheromone_table[keyword][neighbor] * (1 - self.parameters["p"]),
                )
