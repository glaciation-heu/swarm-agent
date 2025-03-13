from os import getenv

METADATA_SERVICE_IP = getenv("METADATA_SERVICE_URL", "metadata-service")
METADATA_SERVICE_PORT = getenv("METADATA_SERVICE_PORT", "80")

MY_NODE_NAME = getenv("MY_NODE_NAME")

MY_POD_IP = getenv("MY_POD_IP", "localhost")
MY_POD_NAME = getenv("MY_POD_NAME", "swarm-agent")
MY_POD_NAMESPACE = getenv("MY_POD_NAMESPACE", "default")

QUERY_NEIGHBORS = """SELECT DISTINCT ?pod WHERE {
    GRAPH <swarm-agent:neighbors> {
        ?pod <swarm:isNeighborOf> ?neighbor
    }
}"""
