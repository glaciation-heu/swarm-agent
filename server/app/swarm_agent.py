from typing import Any, Dict, List

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from pymongo import MongoClient
from rdflib.plugins.sparql.parser import parseQuery

from app.message import Message

# from app.schemas import (
#     ResponseHead,
#     ResponseResults,
#     SearchResponse,
#     SPARQLQuery,
#     UpdateRequestBody,
# )


class SwarmAgent:
    def __init__(self, query: str, parameters_file: str, visited_nodes: List[str] = []):
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
        self.query = query
        self.parameters = self.load_parameters(parameters_file)
        self.keyword = self.transform_query_to_keyword(query)
        self.visited_nodes = visited_nodes
        self.pheromone_table: Dict[str, Any] = {}
        now_utc = datetime.now(timezone.utc)
        self.unique_id = now_utc.strftime("%Y-%m-%d %H:%M:%S.%f")
        self.time_to_live = self.parameters["ttl"]

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

    def get_triples_from_query(self, sparql_query):
        parsed_query = parseQuery(sparql_query)
        triple_pattern = parsed_query[1]["where"]["part"][0]["triples"][0]
        predicate = triple_pattern[1]["part"][0]["part"][0]["part"]
        local_predicate = predicate.split("/")[-1]

        local_object = str(triple_pattern[2]["string"])

        return local_predicate, local_object

    def local_query(self):
        """
        Queries Local Metadata service
        """

        params = {"query": self.query}
        encoded_query = urlencode(params)
        base_url = "http://metadata-service:80/api/v0/graph"
        full_url = f"{base_url}?{encoded_query}"

        response = requests.get(full_url)

        return response

    def get_neighbor_pheromones(self):
        """_summary_
        Reads pheromone table from a MongoDB database to appropriate variable
        """

        client: MongoClient[Dict[str, Any]] = MongoClient("localhost", 27017)
        db = client["SwarmAgent"]
        for keyword in db.pheromone_table.distinct("keyword"):
            neighbors_dict = {}
            db_keyword = db["pheromone_table"].find_one({"keyword": keyword})
            if db_keyword is not None:
                for neighbor in db_keyword["neighbors"]:
                    neighbors_dict[neighbor["neighbor_id"]] = neighbor[
                        "pheromone_value"
                    ]
            self.pheromone_table[keyword] = neighbors_dict

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

        # we need to modify the message
        # update visited nodes list!

        # if request fulfilled create a backward ant message

        # once proper node is chosen we need to send the message further

        return response
