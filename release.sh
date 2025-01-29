#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status.

# 1. Run formatting check with Poetry
echo "Checking formatting requirements with Poetry..."

poetry run mypy server
if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run mypy . --check --diff' to fix them."
    exit 1
fi

poetry run isort server --check --diff

if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run isort . --check --diff' to fix them."
    exit 1
fi

poetry run flake8 server

if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run flake8 .' to fix them."
    exit 1
fi

poetry run black --check server

if [ $? -ne 0 ]; then
    echo "Formatting issues found. Please run 'poetry run black .' to fix them."
    exit 1
fi

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

# 3. Stage changes
echo "Staging changes..."
git add $VERSION_FILE

# Add modified Python files in the server directory
git add server/**/*.py

# 4. Commit changes
echo "Committing changes..."
git commit -m "Release version $NEW_VERSION"

# 5. Tag the new version
echo "Tagging the new version..."
git tag "$NEW_VERSION"

# 6. Push changes and tags to origin
echo "Pushing changes and tags to origin..."
git push origin
git push origin --tags

echo "Release process completed successfully!"