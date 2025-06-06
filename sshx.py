import requests, subprocess, os, time

URL = os.getenv("WEBHOOK_URL")


def get_sshx() -> str:
    process = subprocess.Popen(
        ["sshx"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    for line in process.stdout:
        if not b"sshx.io" in line:
            continue

        return line[line.index(b"http") : -5].decode("UTF-8")


def send_webhook(content: str) -> dict | None:
    req = requests.post(URL + "?wait=true", json={"content": content}, headers={"Content-Type": "application/json"})

    if req.status_code in [200]:
        return req.json()

    return None


if __name__ == "__main__":
    sshx_url = get_sshx()
    webhook_message = send_webhook("🔗 SSHX Tunnel: " + sshx_url)

    with open("/home/runner/.webhook_id", "w") as f:
        f.write(webhook_message["id"])

    while True:
        time.sleep(5)
