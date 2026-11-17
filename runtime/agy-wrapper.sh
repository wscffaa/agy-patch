#!/bin/zsh
# Antigravity CLI wrapper (native Google OAuth + prompt cache keepalive relay; no local gateway).
# The Windows sibling is runtime/agy_wrapper.py behind runtime/agy-wrapper.cmd.
# Delegates binary execution to the single patched Mach-O binary at ~/.local/bin/agy.

# Never let a background update replace the patched binary. Extension-spawned processes
# do not reliably inherit ~/.zshrc. The updater accepts only the exact string "true".
export AGY_CLI_DISABLE_AUTO_UPDATE=true

agy_bin=$HOME/.local/bin/agy

# --hub (VS Code extension) runs directly with native Google OAuth.
if [[ "$*" == *"--hub"* ]]; then
  exec $agy_bin "$@"
fi

# Interactive and ACP sessions send Cloud Code traffic through a per-process loopback relay
# that keeps an idle session's implicit prompt cache warm (agy-patch/runtime/cache_relay.py). Both
# read CLOUD_CODE_URL. Print mode, other subcommands, AGY_CACHE_RELAY=off, and any relay failure
# use direct endpoints.
relay_py=$HOME/.gemini/agy-patch/runtime/cache_relay.py
if [[ "${AGY_CACHE_RELAY:-}" != off && -r $relay_py && ( $# -eq 0 || "$1" == -* || "$1" == "acp" ) ]] &&
   (( ! ${argv[(I)(-p|--print|--prompt|--login|--help|-h)(|=*)]} )); then
  # A nested agy inherits its parent's relay as GOOGLE_GEMINI_BASE_URL; chain to the original.
  relay_parent=${AGY_CACHE_RELAY:-}
  gemini_upstream=${GOOGLE_GEMINI_BASE_URL:-}
  [[ -n $gemini_upstream && $gemini_upstream == "$relay_parent" ]] && gemini_upstream=${AGY_GEMINI_UPSTREAM:-}
  relay_args=(--parent $$)
  [[ -n $gemini_upstream ]] && relay_args+=(--gemini-upstream "$gemini_upstream")
  exec {relay_fd}< <(exec python3 -I $relay_py $relay_args 2>>/tmp/agy_cache_relay.log)
  read -t 3 -u $relay_fd relay_port
  exec {relay_fd}<&-
  if [[ "${relay_port:-}" == <-> ]]; then
    export AGY_CACHE_RELAY="http://127.0.0.1:$relay_port"
    if [[ -n $gemini_upstream ]]; then
      export AGY_GEMINI_UPSTREAM=$gemini_upstream GOOGLE_GEMINI_BASE_URL=$AGY_CACHE_RELAY
    else
      # The inherited value named the parent relay, not a Gemini endpoint; leaving it would
      # bypass this relay, and pointing it here without an upstream would mean Cloud Code.
      unset AGY_GEMINI_UPSTREAM
      [[ -n $relay_parent && ${GOOGLE_GEMINI_BASE_URL:-} == "$relay_parent" ]] && unset GOOGLE_GEMINI_BASE_URL
    fi
    CLOUD_CODE_URL="$AGY_CACHE_RELAY" exec $agy_bin "$@"
  fi
fi

exec $agy_bin "$@"
