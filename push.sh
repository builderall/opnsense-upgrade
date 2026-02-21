#!/bin/bash
# Push to GitHub from WSL using gh CLI token
# Usage: ./push.sh [--tags] [--force]

set -e

REMOTE="origin"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
GITHUB_USER="builderall"
REPO_NAME="opnsense-upgrade"
REPO_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"

# Verify gh is authenticated
if ! gh auth status &>/dev/null; then
  echo "ERROR: Not authenticated. Run: gh auth login"
  exit 1
fi

# Create GitHub repo if it does not exist yet
if ! gh repo view "${GITHUB_USER}/${REPO_NAME}" &>/dev/null; then
  echo "Creating GitHub repo ${GITHUB_USER}/${REPO_NAME}..."
  gh repo create "${REPO_NAME}" --public --description "Stateful multi-stage upgrade script for OPNsense firewalls with automatic recovery and dry-run safety"
fi

# Get token from gh CLI
TOKEN=$(gh auth status -t 2>&1 | grep 'Token:' | awk '{print $NF}')
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not extract token from gh auth"
  exit 1
fi

# Add or update remote
if git remote get-url "$REMOTE" &>/dev/null; then
  git remote set-url "$REMOTE" "https://${GITHUB_USER}:${TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"
else
  git remote add "$REMOTE" "https://${GITHUB_USER}:${TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"
fi

# Parse flags
PUSH_TAGS=false
PUSH_FORCE=false
for arg in "$@"; do
  case "$arg" in
    --tags) PUSH_TAGS=true ;;
    --force) PUSH_FORCE=true ;;
  esac
done

# Build push command
PUSH_CMD="git push -u $REMOTE $BRANCH"
if [ "$PUSH_TAGS" = true ]; then
  PUSH_CMD="$PUSH_CMD --tags"
fi
if [ "$PUSH_FORCE" = true ]; then
  PUSH_CMD="$PUSH_CMD --force"
  echo "WARNING: Force pushing branch '$BRANCH'${PUSH_TAGS:+ + tags} to $REMOTE..."
else
  echo "Pushing branch '$BRANCH'${PUSH_TAGS:+ + tags} to $REMOTE..."
fi

$PUSH_CMD

# Remove token from remote URL
git remote set-url "$REMOTE" "$REPO_URL"

echo "Done. Remote URL cleaned."
