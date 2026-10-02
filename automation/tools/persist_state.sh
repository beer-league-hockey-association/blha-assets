#!/usr/bin/env bash
set -euo pipefail

STATE_PATH="${1:?state path required}"
COMMIT_MESSAGE="${2:?commit message required}"
GIT_USER_NAME="${3:-BLHA Automation}"
GIT_USER_EMAIL="${4:-actions@users.noreply.github.com}"
BRANCH="${GITHUB_REF_NAME:-main}"

# git status (unlike git diff) also reports a brand-new, untracked state file.
if [[ -z "$(git status --porcelain -- "$STATE_PATH")" ]]; then
  echo "No state change for $STATE_PATH."
  exit 0
fi

git config user.name "$GIT_USER_NAME"
git config user.email "$GIT_USER_EMAIL"
git add "$STATE_PATH"
git commit -m "$COMMIT_MESSAGE"

for attempt in 1 2 3; do
  echo "State push attempt $attempt/3 for $STATE_PATH"

  if ! git pull --rebase origin "$BRANCH"; then
    echo "ERROR: rebase failed while persisting $STATE_PATH."
    git rebase --abort >/dev/null 2>&1 || true
    exit 1
  fi

  if git push origin "HEAD:$BRANCH"; then
    echo "State persisted successfully."
    exit 0
  fi

  if [[ "$attempt" -lt 3 ]]; then
    sleep $((attempt * 2))
  fi
done

echo "ERROR: unable to persist $STATE_PATH after 3 push attempts."
exit 1
