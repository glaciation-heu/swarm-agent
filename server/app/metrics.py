from prometheus_client import Counter, Gauge, Histogram

forward_ants_total = Counter(
    "swarm_forward_ants_total",
    "Total forward ant messages received",
)
backward_ants_total = Counter(
    "swarm_backward_ants_total",
    "Total backward ant messages received",
)
# "successful_requests_count" network-traffic proxy from the paper.
# Cluster-wide total: sum(swarm_successful_forwarding_requests_total)
successful_forwarding_requests_total = Counter(
    "swarm_successful_forwarding_requests_total",
    "Successful inter-node ant-forwarding HTTP POSTs (network traffic proxy)",
)
# Labeled by keyword so the experiment repo can break down per dataset.
# Cluster-wide hit count: sum(swarm_query_hits_total)
query_hits_total = Counter(
    "swarm_query_hits_total",
    "Backward ants that completed at origin with non-empty results",
    labelnames=["keyword"],
)
# End-to-end query latency = sum of per-hop link_costs recorded by forward ants.
# Cluster-wide median:
#   histogram_quantile(0.5, sum by(le)(rate(swarm_query_latency_seconds_bucket[5m])))
query_latency_seconds = Histogram(
    "swarm_query_latency_seconds",
    "End-to-end latency of resolved queries (sum of per-hop link costs, seconds)",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300],
    labelnames=["keyword"],
)
# Routing path length for resolved queries only.
# Cluster-wide median:
#   histogram_quantile(0.5, sum by(le)(rate(swarm_ant_path_hops_bucket[5m])))
ant_path_hops = Histogram(
    "swarm_ant_path_hops",
    "Hop count of completed backward ants (visited_nodes length)",
    buckets=[1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25],
    labelnames=["keyword"],
)
queue_depth = Gauge(
    "swarm_queue_depth",
    "Ant messages currently waiting in the processing queue",
)
data_movement_recommendations_total = Counter(
    "swarm_data_movement_recommendations_total",
    "Data movement recommendations issued by the DataMovementAgent",
)
