#!/usr/bin/env bash
# Deploy swarm-agent from local source to a k3d cluster, bypassing CI.
# Builds the Docker image, imports it into the cluster, patches Chart.yaml
# (the CI normally fills in the empty version fields), and runs helm upgrade.

set -o errexit
set -o nounset

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="swarm-agent"
IMAGE_TAG="dev"
RELEASE_NAME="swarm-agent"
CHART_PATH="$ROOT/server/charts/server"
DOCKERFILE_CONTEXT="$ROOT/server"
NAMESPACE="dkg-engine"
K3D_CLUSTER=""
NUM_DATASETS=1
SKIP_BUILD=false
SKIP_IMPORT=false
RANDOM_WALK=false

# ACO algorithm parameters (match parameters.json defaults)
PHEROMONE_EVAPORATION=0.1
W_EXPLOIT=0.5
BETA=1.0
W_D=0.5
T_MAX=3.0
R_MAX=10.0

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Build, import, and deploy the swarm-agent Helm chart to a local k3d cluster.

Options:
  -c, --cluster <name>       k3d cluster name (default: auto-detect first running cluster)
  -t, --tag <tag>            Docker image tag (default: dev)
  -n, --namespace <ns>       Kubernetes namespace (default: dkg-engine)
  --num-datasets <n>         Number of data items injected at setup (default: 1)
  --skip-build               Skip docker build (use existing local image)
  --skip-import              Skip k3d image import (image already in cluster)

  ACO parameters (override individual algorithm knobs):
  --evaporation <rate>       Pheromone evaporation rate rho (default: 0.1)
  --w-exploit <prob>         Exploit probability (default: 0.5)
  --beta <exp>               Pheromone exponent in goodness g=tau^beta (default: 1.0)
  --w-d <weight>             Result vs path-efficiency weight in deposit (default: 0.5)
  --t-max <seconds>          Reference path cost for deposit formula (default: 3.0)
  --r-max <count>            Result count normalisation constant (default: 10.0)

  --random-walk              Shortcut: sets evaporation=1.0, w-exploit=0.0, beta=0.0.
                             Makes neighbor selection perfectly uniform regardless of
                             any accumulated pheromone. Use for the baseline condition.

  -h, --help                 Show this help and exit

Examples:
  # Swarm ACO run, single dataset:
  $(basename "$0") -c my-cluster

  # Multi-keyword experiment with 5 datasets:
  $(basename "$0") -c my-cluster --num-datasets 5

  # Random walk baseline (for comparison against swarm):
  $(basename "$0") -c my-cluster --random-walk

  # Random walk with 5 datasets:
  $(basename "$0") -c my-cluster --random-walk --num-datasets 5

  # Quick re-deploy after a code change (no rebuild):
  $(basename "$0") -c my-cluster --skip-build --skip-import
  kubectl rollout restart daemonset/swarm-agent
EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -c|--cluster)      K3D_CLUSTER="$2";           shift 2 ;;
            -t|--tag)          IMAGE_TAG="$2";              shift 2 ;;
            -n|--namespace)    NAMESPACE="$2";              shift 2 ;;
            --num-datasets)    NUM_DATASETS="$2";           shift 2 ;;
            --evaporation)     PHEROMONE_EVAPORATION="$2";  shift 2 ;;
            --w-exploit)       W_EXPLOIT="$2";              shift 2 ;;
            --beta)            BETA="$2";                   shift 2 ;;
            --w-d)             W_D="$2";                    shift 2 ;;
            --t-max)           T_MAX="$2";                  shift 2 ;;
            --r-max)           R_MAX="$2";                  shift 2 ;;
            --random-walk)     RANDOM_WALK=true;            shift   ;;
            --skip-build)      SKIP_BUILD=true;             shift   ;;
            --skip-import)     SKIP_IMPORT=true;            shift   ;;
            -h|--help)         usage ;;
            *) echo "Unknown option: $1"; echo ""; usage ;;
        esac
    done

    if [ "$RANDOM_WALK" = true ]; then
        PHEROMONE_EVAPORATION=1.0
        W_EXPLOIT=0.0
        BETA=0.0
    fi
}

detect_cluster() {
    if [ -n "$K3D_CLUSTER" ]; then
        return
    fi
    K3D_CLUSTER=$(
        k3d cluster list -o json 2>/dev/null \
        | python3 -c "
import sys, json
clusters = [c['name'] for c in json.load(sys.stdin) if c.get('serversRunning', 0) > 0]
print(clusters[0] if clusters else '')
" 2>/dev/null || true
    )
    if [ -z "$K3D_CLUSTER" ]; then
        echo "ERROR: no running k3d cluster found. Start one first or pass -c <name>."
        exit 1
    fi
    echo "Auto-detected k3d cluster: $K3D_CLUSTER"
}

patch_chart_yaml() {
    # The CI fills in version/appVersion via version.sh; for local deploys we
    # set a placeholder so Helm does not reject the empty SemVer strings.
    local chart_file="$CHART_PATH/Chart.yaml"
    if grep -q 'version: ""' "$chart_file"; then
        sed -i 's/version: ""/version: "0.0.0-local"/' "$chart_file"
        echo "Patched Chart.yaml: version → 0.0.0-local"
    fi
    if grep -q 'appVersion: ""' "$chart_file"; then
        sed -i 's/appVersion: ""/appVersion: "0.0.0-local"/' "$chart_file"
        echo "Patched Chart.yaml: appVersion → 0.0.0-local"
    fi
}

main() {
    parse_args "$@"

    if [ "$SKIP_IMPORT" = false ]; then
        detect_cluster
    fi

    echo "==> Configuration:"
    echo "    mode:               $([ "$RANDOM_WALK" = true ] && echo 'random walk' || echo 'swarm ACO')"
    echo "    num_datasets:       $NUM_DATASETS"
    echo "    pheromone_evap (p): $PHEROMONE_EVAPORATION"
    echo "    w_exploit:          $W_EXPLOIT"
    echo "    beta:               $BETA"
    echo "    w_d:                $W_D"
    echo "    t_max:              $T_MAX"
    echo "    r_max:              $R_MAX"

    if [ "$SKIP_BUILD" = false ]; then
        echo "==> Building Docker image ${IMAGE_NAME}:${IMAGE_TAG} ..."
        docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" "$DOCKERFILE_CONTEXT"
    fi

    if [ "$SKIP_IMPORT" = false ]; then
        echo "==> Importing image into k3d cluster '${K3D_CLUSTER}' ..."
        k3d image import "${IMAGE_NAME}:${IMAGE_TAG}" -c "$K3D_CLUSTER"
    fi

    patch_chart_yaml

    echo "==> Deploying Helm chart (release: ${RELEASE_NAME}, namespace: ${NAMESPACE}) ..."
    helm upgrade --install "$RELEASE_NAME" "$CHART_PATH" \
        --namespace "$NAMESPACE" \
        --create-namespace \
        --set image.repository="$IMAGE_NAME" \
        --set image.tag="$IMAGE_TAG" \
        --set image.pullPolicy=Never \
        --set envVariables.numDatasets="$NUM_DATASETS" \
        --set envVariables.pheromoneEvaporation="$PHEROMONE_EVAPORATION" \
        --set envVariables.wExploit="$W_EXPLOIT" \
        --set envVariables.beta="$BETA" \
        --set envVariables.wD="$W_D" \
        --set envVariables.tMax="$T_MAX" \
        --set envVariables.rMax="$R_MAX"

    echo "==> Restarting DaemonSet to pick up new image ..."
    kubectl rollout restart daemonset/"${RELEASE_NAME}" -n "${NAMESPACE}"
    kubectl rollout status daemonset/"${RELEASE_NAME}" -n "${NAMESPACE}"

    echo ""
    echo "==> Deployed successfully."
}

main "$@"
