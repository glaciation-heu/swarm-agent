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

PHEROMONE_THRESHOLD = float(getenv("PHEROMONE_THRESHOLD", "1e-5"))
PARAMETER_ENV_VARIABLES = {"PHEROMONE_EVAPORATION": {"key": "p", "default": "0.1"}}

REMOVE_VISITATION_THRESHOLD = float(getenv("REMOVE_VISITATION_THRESHOLD", "86400000"))
REMOVE_VISITATION_QUERY = f"""
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

DELETE {{
  GRAPH <swarm-agent:visitation> {{
    ?nodeID <swarm:wasVisitedBy> ?agentID .
    ?visit <swarm:visitedAt> ?ts .
    ?visit <swarm:hasNodeID> ?nodeID .
    ?visit <swarm:hasAgentID> ?agentID .
  }}
}}
WHERE {{
  GRAPH <swarm-agent:visitation> {{
    ?nodeID <swarm:wasVisitedBy> ?agentID .
    ?visit <swarm:visitedAt> ?ts .
    ?visit <swarm:hasNodeID> ?nodeID .
    ?visit <swarm:hasAgentID> ?agentID .

    FILTER (datatype(?ts) = xsd:integer)

    BIND(NOW() - "1970-01-01T00:00:00Z"^^xsd:dateTime AS ?diff)
    BIND((
        SECONDS(?diff)
        + MINUTES(?diff) * 60
        + HOURS(?diff) * 3600
        + DAY(?diff) * 86400
    ) * 1000 AS ?nowMs)


    FILTER (?ts < (?nowMs - {REMOVE_VISITATION_THRESHOLD}))
  }}
}}
"""
