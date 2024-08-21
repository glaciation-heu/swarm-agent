import re
import json
import os
import requests
from urllib.parse import urlencode
from pymongo import MongoClient

class SwarmAgent:
    def __init__(self, query: str, parameters_file: str):
        """
        The function initializes an object with a query, parameters loaded from a file, time to live value,
        and a keyword derived from the query.
        
        :param query: The `query` parameter is a string that represents the search query in SPARQL language
        :type query: str
        :param parameters_file: The `parameters_file` is a file containing the parameters needed for the
        query. When the `__init__` method is called, the `load_parameters` method is used to load these
        parameters from the specified file. File is in json format which is basically a dictionary
        :type parameters_file: str      
        """
        self.query = query
        self.parameters = self.load_parameters(parameters_file)
        self.keyword = self.transform_query_to_keyword(query)
        self.visited_nodes=[]
        self.pheromone_table = {}

    def load_parameters(self, file_path: str) -> dict:
        """
        The `load_parameters` function reads and loads parameters from a JSON file into a dictionary.
        
        :param file_path: The `load_parameters` function takes a file path as input and reads the contents
        of the file using the `json.load` method. It then returns the loaded data as a dictionary
        :type file_path: str
        :return: The `load_parameters` method is returning a dictionary containing the parameters loaded
        from the JSON file specified by the `file_path` argument.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")
        with open(file_path, 'r') as file:
            return json.load(file)

    def transform_query_to_keyword(self, query):
        """
        The function `transform_query_to_keyword` extracts keywords from a query string.
        
        :param query: the function `transform_query_to_keyword` is designed to extract
        specific parts from a query string and transform them into a keyword. The function uses regular
        expressions to find text within curly braces `{}` in the query string, then processes and
        concatenates certain parts of the extracted text to form the
        :return: The function `transform_query_to_keyword` returns a keyword based on the input query. The
        keyword is generated by extracting specific parts of the query and combining them in a certain way.
        """

        matches = re.findall(r"\{(.*?)\}", query)
        query_string = [elem for elem in matches[0].split(" ") if len(elem) > 1]

        q_sub, q_pre, q_obj = query_string[0:3]

        keyword = ""
        if "?" not in q_pre:
            keyword += q_pre.split(":")[1]
        if "?" not in q_obj:
            keyword += "_" + q_obj.split("^^")[0].replace('"', "")

        return keyword
    
    def local_query(self):
        
        params = {"query": self.query}
        encoded_query = urlencode(params)
        base_url = "http://127.0.0.1:8001/api/v0/graph"
        full_url = f"{base_url}?{encoded_query}"
        
        print(full_url)

        
        response = requests.get(full_url)
        
        print(response)
        
        return response
    
    def get_neighbor_pheromones(self):
        """_summary_
        Reads pheromone table from a MongoDB database to appropriate variable
        """

        client = MongoClient('localhost', 27017)
        db = client['SwarmAgent']
        for keyword in db.pheromone_table.distinct("keyword"):
            neighbors_dict = {}
            for neighbor in db["pheromone_table"].find_one({"keyword":keyword})["neighbors"]:
                neighbors_dict[neighbor["neighbor_id"]] = neighbor["pheromone_value"]
                print(neighbor["neighbor_id"], neighbor["pheromone_value"]) 
            self.pheromone_table[keyword] = neighbors_dict


    
    def step(self):
        response = self.local_query()
        self.get_neighbor_pheromones()
        print("pheromone_table", self.pheromone_table)
        return response


