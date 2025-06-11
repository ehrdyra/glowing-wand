if [[ -z "$1" ]]; then
  echo "Bruh, you forgot the port number! 😩"
  echo "Usage: $0 <port>"
  exit 1
fi

CLOUDFLARED_LAUNCH_LOG="/tmp/cloudflared_launch_attempt.log"
URL_OUTPUT_FILE="/workspace/.webaddr"

rm -f "$CLOUDFLARED_LAUNCH_LOG"

cloudflared tunnel --url http://localhost:$1 --no-autoupdate > "$CLOUDFLARED_LAUNCH_LOG" 2>&1 &
CLOUDFLARED_PID=$!

if [[ -z "$CLOUDFLARED_PID" ]]; then
  exit 1
fi

public_url=""
SECONDS_WAITED=0
MAX_WAIT=30

while [[ -z "$public_url" && $SECONDS_WAITED -lt $MAX_WAIT ]]; do
  if ! kill -0 "$CLOUDFLARED_PID" 2>/dev/null; then
    exit 1
  fi

  if [[ -f "$CLOUDFLARED_LAUNCH_LOG" ]]; then
    _match=$(grep -oE 'https?://[-A-Za-z0-9_.]+trycloudflare\.com' "$CLOUDFLARED_LAUNCH_LOG" | head -n 1)
    if [[ -n "$_match" ]]; then
      public_url="$_match"
      break
    fi
  fi

  sleep 1
  SECONDS_WAITED=$((SECONDS_WAITED + 1))
done

if ! kill -0 "$CLOUDFLARED_PID" 2>/dev/null; then
  exit 1
fi

if [[ -n "$public_url" ]]; then
  echo "$public_url" > "$URL_OUTPUT_FILE"
  disown "$CLOUDFLARED_PID"
  exit 0
else
  kill "$CLOUDFLARED_PID"
  wait "$CLOUDFLARED_PID" 2>/dev/null
  exit 1
fi
