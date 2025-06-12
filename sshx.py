import subprocess


def get_sshx() -> tuple[subprocess.Popen, str]:
    process = subprocess.Popen(
        ["sshx"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    for line in process.stdout:
        if not b"sshx.io" in line:
            continue

        return process, line[line.index(b"http") : -5].decode("UTF-8")

    process.kill()
    raise RuntimeError()


if __name__ == "__main__":
    proc, url = get_sshx()

    with open(".sshx_url", "w") as file:
        file.write(url)
