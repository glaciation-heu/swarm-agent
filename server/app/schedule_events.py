from os import environ
from time import sleep

import schedule
from loguru import logger

from app.consts import REMOVE_VISITATION_QUERY
from app.create_neighbors import create_neighbors
from app.data_movement import DataMovementAgent
from app.schemas import Message
from app.swarm_agent import SwarmAgent
from app.utils import metadata_service_url, send_message

if "KUBERNETES_SERVICE_HOST" in environ:
    try:
        swarm_agent = SwarmAgent(Message(), "app/parameters.json")
    except FileNotFoundError:
        swarm_agent = SwarmAgent(Message(), "server/app/parameters.json")


def evap_pheromones():
    try:
        swarm_agent.pheromone_evaporation()
    except Exception:
        logger.exception("An error occured")


def move_data():
    try:
        agent = DataMovementAgent()
        agent.check_pheromone_strengths()
    except Exception:
        logger.exception("An error occured")


def remove_visitation_entries():
    try:
        logger.info("Removing visitation entries.")
        logger.debug(REMOVE_VISITATION_QUERY)
        send_message(
            {"query": REMOVE_VISITATION_QUERY},
            metadata_service_url(),
            "api/v0/graph/update",
        )
    except Exception:
        logger.exception("An error occured")


# TODO data movement recommendation - regular pheromone map checks
schedule.every(60).seconds.do(evap_pheromones)
schedule.every(60).seconds.do(create_neighbors)
schedule.every(300).seconds.do(move_data)
schedule.every(3600).seconds.do(remove_visitation_entries)

if __name__ == "__main__":
    while True:
        schedule.run_pending()
        sleep(1)
