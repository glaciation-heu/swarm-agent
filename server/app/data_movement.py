from typing import Any

from collections import deque
from threading import Lock

import numpy as np
from loguru import logger

from app.consts import MY_POD_IP, MY_POD_NAME
from app.metrics import data_movement_recommendations_total
from app.schemas import DataMovementRecommendation, SearchResponse
from app.utils import get_pheromone_table, get_swarm_agent_neighbors, send_message

# Thread-safe store of recent recommendations (capped at 100 entries).
_recommendations: deque[DataMovementRecommendation] = deque(maxlen=100)
_recommendations_lock = Lock()


def get_recent_recommendations() -> list[DataMovementRecommendation]:
    with _recommendations_lock:
        return list(_recommendations)


class DataMovementAgent:
    def __init__(self):
        self.this_node = MY_POD_NAME
        self.this_node_ip = MY_POD_IP

        self.neighbors = get_swarm_agent_neighbors(self.this_node, self.this_node_ip)

    def get_neighbor_pheromones(self):
        message = {"neighbor": self.this_node}

        self.neighbor_pheromones: dict[str, list[Any]] = {}

        for neighbor in self.neighbors:
            response = send_message(
                message, f"http://{neighbor['ip']}:80", "api/v0/pheromone"
            )

            results = None
            if response.status_code == 200:
                results = SearchResponse.model_validate_json(response.text)
            else:
                logger.error(f"Error: {response.status_code}, {response.text}")

            if results is not None:
                logger.debug(
                    (
                        f"Found pheromones pointing from \"{neighbor['name']}\" "
                        f'to this node ("{self.this_node}"):\n'
                        f"{results.model_dump_json(indent=2)}"
                    )
                )

                for result in results.results.bindings:
                    keyword = result["keyword"]["value"]
                    ph_value = float(result["pheromone_value"]["value"])
                    try:
                        self.neighbor_pheromones[keyword].append(
                            {"neighbor": neighbor, "pheromone_value": ph_value}
                        )
                    except KeyError:
                        self.neighbor_pheromones[keyword] = [
                            {"neighbor": neighbor, "pheromone_value": ph_value}
                        ]

    def reshape_pheromone_tables(self, pheromones, neighbor_pheromones):
        neighbor_dict = {}
        my_pheromone_values = np.empty(len(self.neighbors))
        neighbor_pheromone_values = np.zeros(len(self.neighbors))

        for i, neighbor in enumerate(self.neighbors):
            neighbor_dict[neighbor["name"]] = i
            try:
                my_pheromone_values[i] = pheromones[neighbor["name"]]
            except KeyError:
                my_pheromone_values[i] = 0

        for entry in neighbor_pheromones:
            neighbor_pheromone_values[neighbor_dict[entry["neighbor"]["name"]]] = entry[
                "pheromone_value"
            ]

        return my_pheromone_values, neighbor_pheromone_values

    def check_pheromone_strengths(self):
        self.pheromone_table = get_pheromone_table(self.this_node, self.neighbors)
        self.get_neighbor_pheromones()

        for keyword in self.neighbor_pheromones:
            logger.info(
                "Checking pheromone pull for keyword "
                f"'{keyword}' on node '{self.this_node}'."
            )
            my_pheromones, neighbor_pheromones = self.reshape_pheromone_tables(
                self.pheromone_table[keyword], self.neighbor_pheromones[keyword]
            )

            mean_neighbor_pheromones = neighbor_pheromones.mean()

            no_data_movement = True
            if mean_neighbor_pheromones > 0:
                fulfills_condition = np.where(
                    2.0 * neighbor_pheromones - my_pheromones
                    >= (1.0 + neighbor_pheromones.size) * mean_neighbor_pheromones
                )[0]

                if fulfills_condition.size == 1:
                    no_data_movement = False
                    moving_to = self.neighbors[fulfills_condition[0]]
                    logger.info(
                        f"Data movement recommendation: '{self.this_node}' → "
                        f"'{moving_to['name']}' (keyword: '{keyword}'). "
                        "Advisory only — no data moved autonomously."
                    )
                    rec = DataMovementRecommendation(
                        keyword=keyword,
                        from_node=self.this_node,
                        to_node=moving_to["name"],
                    )
                    with _recommendations_lock:
                        _recommendations.append(rec)
                    data_movement_recommendations_total.inc()
                elif fulfills_condition.size > 1:
                    logger.info(
                        "Multiple nodes fulfill data movement condition. "
                        "Not moving the data."
                    )

            if no_data_movement:
                logger.info("None of the nodes fulfill data movement condition.")
