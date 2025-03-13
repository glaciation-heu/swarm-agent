# TODO develop data movement recommendation here
from loguru import logger

from app.consts import MY_POD_IP, MY_POD_NAME
from app.schemas import SearchResponse
from app.utils import get_swarm_agent_neighbors, send_message


class DataMovementAgent:
    def __init__(self):
        self.this_node = MY_POD_NAME
        self.this_node_ip = MY_POD_IP

        self.neighbors = get_swarm_agent_neighbors(self.this_node, self.this_node_ip)

    def check_pheromone_strengths(self):
        message = {"neighbor": self.this_node}

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
