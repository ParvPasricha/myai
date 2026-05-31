# PARV-AI shell hook
# Sends every completed command to the AI for passive learning.
#
# Install: add this line to ~/.zshrc
#   source /Users/parvpasricha/Desktop/myai/shell/parv_hook.zsh

_PARV_API="http://localhost:8000"
_PARV_TOKEN_FILE="$HOME/.parv_ai_token"
_PARV_CMD_START=0
_PARV_LAST_CMD=""

# Cache auth token (refresh if file is older than 23h)
_parv_token() {
  if [[ -f "$_PARV_TOKEN_FILE" ]]; then
    local age=$(( $(date +%s) - $(stat -f %m "$_PARV_TOKEN_FILE" 2>/dev/null || echo 0) ))
    if (( age < 82800 )); then
      cat "$_PARV_TOKEN_FILE"
      return
    fi
  fi
  local tok
  tok=$(curl -s -X POST "$_PARV_API/auth/token" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null)
  [[ -n "$tok" ]] && echo "$tok" > "$_PARV_TOKEN_FILE"
  echo "$tok"
}

# Capture command before it runs
preexec() {
  _PARV_CMD_START=$SECONDS
  _PARV_LAST_CMD="$1"
}

# Send observation after command completes
precmd() {
  local exit_code=$?
  local cmd="$_PARV_LAST_CMD"
  [[ -z "$cmd" ]] && return

  local duration=$(( SECONDS - _PARV_CMD_START ))
  local cwd="$PWD"
  local token
  token=$(_parv_token 2>/dev/null)
  [[ -z "$token" ]] && return

  # Fire and forget — don't slow the shell
  (
    curl -s -X POST "$_PARV_API/observe/terminal" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d "{\"command\":$(echo -n "$cmd" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"exit_code\":$exit_code,\"cwd\":$(echo -n "$cwd" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"duration_s\":$duration}" \
      --max-time 2 > /dev/null 2>&1
  ) &!

  _PARV_LAST_CMD=""
}

# Manual: parv-learn <topic>  — trigger deep topic research
parv-learn() {
  local topic="$*"
  [[ -z "$topic" ]] && echo "Usage: parv-learn <topic>" && return 1
  local token
  token=$(_parv_token 2>/dev/null)
  echo "Starting research: $topic"
  curl -s -X POST "$_PARV_API/learn/topic" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{\"topic\":$(echo -n "$topic" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"depth\":\"intermediate\"}" \
    | python3 -m json.tool 2>/dev/null
}

# Manual: parv-status — show what the AI has learned recently
parv-status() {
  local token
  token=$(_parv_token 2>/dev/null)
  curl -s "$_PARV_API/observe/stats" \
    -H "Authorization: Bearer $token" \
    | python3 -m json.tool 2>/dev/null
}
