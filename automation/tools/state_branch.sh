#!/usr/bin/env bash
# Keep automation state on the `automation-state` branch instead of `main`.
#
#   state_branch.sh restore <path>...
#       Copy each path from the state branch into the working tree before a
#       run. Paths missing from the branch are left as they are. A path may be
#       a folder (for example archive), restored with everything in it.
#       With BLHA_STATE_STRICT=1 the restore fails instead of carrying on when
#       the branch exists but cannot be fetched, so a run that appends to a
#       saved file (the league archive) never starts from an empty copy.
#
#   state_branch.sh remove "<commit message>" "<author name>" <path>...
#       Delete each path from the state branch (used by the season rollover).
#
#   state_branch.sh save "<commit message>" "<author name>" <path>...
#       Commit each path to the state branch and push, retrying if another
#       workflow pushed first. JSON files whose only change is a top-level
#       "updated_at" value are not committed. A folder path saves every file
#       in it (files are added or updated, never deleted).
#
# This keeps `main` free of bot commits (the Wire alone used to add up to ~100
# a day) and means state saves never conflict with code changes on `main`.
set -euo pipefail

BRANCH="${BLHA_STATE_BRANCH:-automation-state}"
REMOTE="${BLHA_STATE_REMOTE:-origin}"

fetch_branch() {
  git fetch -q --depth=1 "$REMOTE" "$BRANCH" 2>/dev/null
}

restore() {
  if ! fetch_branch; then
    if [[ "${BLHA_STATE_STRICT:-0}" == "1" ]]; then
      local rc=0
      git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1 || rc=$?
      if [[ $rc -ne 2 ]]; then
        echo "ERROR: could not fetch $BRANCH (it exists or GitHub could not be reached); not starting from an empty copy." >&2
        return 1
      fi
    fi
    echo "State branch $BRANCH not found; using the repository copies."
    return 0
  fi
  for path in "$@"; do
    if [[ "$(git cat-file -t "FETCH_HEAD:$path" 2>/dev/null)" == "tree" ]]; then
      mkdir -p "$path"
      git archive FETCH_HEAD "$path" | tar -x -C "$(git rev-parse --show-toplevel)"
      echo "Restored folder $path from $BRANCH ($(find "$path" -type f | wc -l | tr -d ' ') files)."
    elif git cat-file -e "FETCH_HEAD:$path" 2>/dev/null; then
      mkdir -p "$(dirname "$path")"
      git show "FETCH_HEAD:$path" > "$path"
      echo "Restored $path from $BRANCH."
    else
      echo "No $path on $BRANCH yet; starting from the repository copy (if any)."
    fi
  done
}

same_ignoring_updated_at() {  # <new file> <old file>
  python3 - "$1" "$2" <<'PY'
import json, sys
try:
    new, old = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
except Exception:
    sys.exit(1)
if isinstance(new, dict) and isinstance(old, dict):
    new.pop("updated_at", None)
    old.pop("updated_at", None)
sys.exit(0 if new == old else 1)
PY
}

save() {
  local message="$1" author="$2"
  shift 2
  local repo_root
  repo_root="$(git rev-parse --show-toplevel)"

  for attempt in 1 2 3 4 5; do
    local work
    work="$(mktemp -d)"
    if fetch_branch; then
      git worktree add -q --detach "$work" FETCH_HEAD
    else
      git worktree add -q --detach "$work" HEAD
      (cd "$work" && git checkout -q --orphan "$BRANCH" && git rm -rqf . >/dev/null)
    fi

    for path in "$@"; do
      if [[ -d "$repo_root/$path" ]]; then
        mkdir -p "$work/$path"
        cp -R "$repo_root/$path/." "$work/$path/"
        (cd "$work" && git add -A -- "$path")
        continue
      fi
      [[ -f "$repo_root/$path" ]] || { echo "Skip $path (not present)."; continue; }
      if [[ -f "$work/$path" && "$path" == *.json ]] && same_ignoring_updated_at "$repo_root/$path" "$work/$path"; then
        echo "Only updated_at changed in $path; not saving."
        continue
      fi
      mkdir -p "$work/$(dirname "$path")"
      cp "$repo_root/$path" "$work/$path"
      (cd "$work" && git add -- "$path")
    done

    local pushed=1
    (
      cd "$work"
      if git diff --cached --quiet; then
        echo "No state changes to save."
        exit 0
      fi
      git -c user.name="$author" -c user.email="actions@users.noreply.github.com" commit -q -m "$message"
      git push -q "$REMOTE" "HEAD:refs/heads/$BRANCH"
      echo "State saved to $BRANCH."
    ) && pushed=0

    git worktree remove --force "$work" >/dev/null 2>&1 || rm -rf "$work"
    git worktree prune >/dev/null 2>&1 || true
    if [[ $pushed -eq 0 ]]; then
      return 0
    fi
    echo "Save attempt $attempt failed (another workflow probably saved first); retrying."
    sleep $((attempt * 2))
  done
  echo "ERROR: could not save state to $BRANCH after 5 attempts." >&2
  return 1
}

remove() {
  local message="$1" author="$2"
  shift 2
  for attempt in 1 2 3; do
    local work
    work="$(mktemp -d)"
    if ! fetch_branch; then
      echo "State branch $BRANCH not found; nothing to remove."
      return 0
    fi
    git worktree add -q --detach "$work" FETCH_HEAD
    local pushed=1
    (
      cd "$work"
      for path in "$@"; do
        if git cat-file -e "HEAD:$path" 2>/dev/null; then
          git rm -q -- "$path"
          echo "Removed $path from $BRANCH."
        else
          echo "No $path on $BRANCH; nothing to remove."
        fi
      done
      if git diff --cached --quiet; then
        exit 0
      fi
      git -c user.name="$author" -c user.email="actions@users.noreply.github.com" commit -q -m "$message"
      git push -q "$REMOTE" "HEAD:refs/heads/$BRANCH"
    ) && pushed=0
    git worktree remove --force "$work" >/dev/null 2>&1 || rm -rf "$work"
    git worktree prune >/dev/null 2>&1 || true
    [[ $pushed -eq 0 ]] && return 0
    sleep $((attempt * 2))
  done
  echo "ERROR: could not remove state from $BRANCH." >&2
  return 1
}

command="${1:-}"
shift || true
case "$command" in
  restore) restore "$@" ;;
  save) save "$@" ;;
  remove) remove "$@" ;;
  *) echo "usage: state_branch.sh restore <path>... | save <message> <author> <path>... | remove <message> <author> <path>..." >&2; exit 2 ;;
esac
