#!/bin/bash

WEBHOOK_URL="$WEBHOOK_URL"

# Create a pipe for inter-process communication
pipe=$(mktemp -u)
mkfifo "$pipe"

# Start sshx in background and pipe its output
# - Print both stdout and stderr to our pipe
# curl -sSf https://sshx.io/get | sh -s run 2>&1 | tee "$pipe" &
sshx 2>&1 | tee "$pipe" &

# Read from the pipe and extract the URL
while read -r line; do
    cleaned=$(echo "$line" | sed -r 's/\x1B\[[0-9;]*[mK]//g')

    if [[ "$cleaned" =~ (https://[^ ]*sshx\.io[^ ]*) ]]; then
        sshx_url="${BASH_REMATCH[1]}"
        echo "[+] Found SSHX URL: $sshx_url"
        payload=$(jq -n --arg content "🔗 SSHX Tunnel: $sshx_url" '{content: $content}')
        curl -X POST -H "Content-Type: application/json" -d "$payload" "$WEBHOOK_URL"

        break
    fi
done < "$pipe"

# Cleanup
rm "$pipe"
wait
