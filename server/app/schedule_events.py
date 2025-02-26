from os import environ
from time import sleep

import schedule
from loguru import logger

from app.create_neighbors import create_neighbors
from app.schemas import Message
from app.swarm_agent import SwarmAgent

if "KUBERNETES_SERVICE_HOST" in environ:
    try:
        swarm_agent = SwarmAgent(Message(), "app/parameters.json")
    except FileNotFoundError:
        swarm_agent = SwarmAgent(Message(), "server/app/parameters.json")


def evap_pheromones():
    try:
        swarm_agent.pheromone_evaporation()
    except Exception as e:
        logger.error(str(e))


schedule.every(5).seconds.do(evap_pheromones)
schedule.every(1).minutes.do(create_neighbors)

if __name__ == "__main__":
    while True:
        schedule.run_pending()
        sleep(1)
