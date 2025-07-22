#!/bin/bash

set -euo pipefail  # Exit immediately if a command exits with a non-zero status.


if [ -z "${1:-}" ]; then
  echo "USAGE: $0 \"Your commit message\""
  exit 1
fi

COMMIT_MSG="$1"


# 1. Run formatting check with Poetry
echo "Checking formatting requirements with Poetry..."
cd server
poetry run mypy .
if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run mypy . --check --diff' to fix them."
    exit 1
fi

poetry run isort . --check --diff

if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run isort . --check --diff' to fix them."
    exit 1
fi

poetry run flake8 .

if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run flake8 .' to fix them."
    exit 1
fi

poetry run black --check .

if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run black .' to fix them."
    exit 1
fi

cd ..

# 2. Increment version in VERSION file
VERSION_FILE="VERSION"
if [ ! -f "$VERSION_FILE" ]; then
    echo "VERSION file not found!"
    exit 1
fi

CURRENT_VERSION=$(cat $VERSION_FILE)
IFS='.' read -r -a version_parts <<< "$CURRENT_VERSION"
LAST_PART=${version_parts[-1]}
NEW_LAST_PART=$((LAST_PART + 1))
version_parts[-1]=$NEW_LAST_PART
NEW_VERSION=$(IFS='.'; echo "${version_parts[*]}")

echo "Updating version: $CURRENT_VERSION -> $NEW_VERSION"
echo "$NEW_VERSION" > $VERSION_FILE

echo "Updating 'api/openapi.yaml'"
poetry --directory server run python ../tools/extract_openapi.py app.main:app --app-dir ../server --out ../api/openapi.yaml --app_version_file ../$VERSION_FILE

# 3. Stage changes
echo "Staging changes..."
git add $VERSION_FILE

# Add modified Python files in the server directory
git add server/**/*.py
git add api/openapi.yaml

# 4. Commit changes
echo "Committing changes..."
git commit -m "$COMMIT_MSG"

# 5. Tag the new version
echo "Tagging the new version..."
git tag "$NEW_VERSION"

# 6. Push changes and tags to origin
echo "Pushing changes and tags to origin..."
git push origin
git push origin --tags

echo "Release process completed successfully!"