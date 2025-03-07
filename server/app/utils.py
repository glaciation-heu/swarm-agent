from os import environ, getenv

from kubernetes import client, config
from loguru import logger

METADATA_SERVICE_IP = getenv("METADATA_SERVICE_URL", "metadata-service")
METADATA_SERVICE_PORT = getenv("METADATA_SERVICE_PORT", "80")
MY_NODE_NAME = getenv("MY_NODE_NAME")
MY_POD_NAMESPACE = getenv("MY_POD_NAMESPACE", "default")


def find_metadata_service_ip():
    if "KUBERNETES_SERVICE_HOST" in environ:
        config.load_incluster_config()
    else:
        logger.error("Not running in a Kubernetes cluster.")
        return

    # Initialize the API client
    v1 = client.CoreV1Api()

    # List Metadata Service pods in their namespace
    label_selector = "app.kubernetes.io/name=metadata-service"
    pods = v1.list_namespaced_pod(MY_POD_NAMESPACE, label_selector=label_selector)

    addresses = {pod.spec.node_name: pod.status.pod_ip for pod in pods.items}

    if MY_NODE_NAME in addresses:
        return addresses[MY_NODE_NAME]
    else:
        logger.warning(f"Metadata Service could not be found on node '{MY_NODE_NAME}'.")
        return


def metadata_service_url():
    ip = find_metadata_service_ip()

    if ip is None:
        ip = METADATA_SERVICE_IP

    url = f"http://{ip}:{METADATA_SERVICE_PORT}"
    logger.info(f"Using for Metadata Service: {url}")

    return url
