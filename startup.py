import json
import os
import subprocess
import asyncio
from pathlib import Path
import datetime
import stat
import shutil


async def start_machine_container(machine_info: dict):
    """
    Starts a Docker container for a given machine based on its info.
    This function largely replicates the Docker start logic from main.py.
    """
    machine_id = machine_info.get("id")
    name = machine_info.get("name", f"machine-{machine_id}")
    docker_image = machine_info.get("docker_image")
    ram = machine_info.get("ram", "N/A")
    core = machine_info.get("core", "N/A")
    settings = machine_info.get("settings", {})

    if not docker_image:
        print(f"WARNING: Machine {name} ({machine_id}) has no Docker image specified. Skipping start.")
        return False  # Return False as it failed to start

    container_dir_name = f"container-{machine_id}"
    container_path = Path("workspace") / container_dir_name
    instance_info_path = container_path / "instance_info.json"
    host_files_path = container_path / "files"

    if not container_path.exists():
        print(f"WARNING: Container directory {container_path} not found for machine {machine_id}. Skipping start.")
        return False  # Return False as it failed to start

    # Ensure host_files_path exists
    host_files_path.mkdir(parents=True, exist_ok=True)

    install_command = settings.get("install_command", "")
    build_command = settings.get("build_command", "")
    run_command_setting = settings.get("run_command", "")

    dockerfile_content = f"""FROM {docker_image}

ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    LANG=C.UTF-8 \\
    LC_ALL=C.UTF-8 \\
    TZ=UTC \\
    DEBIAN_FRONTEND=noninteractive

WORKDIR /workspace

COPY files/ .
COPY tunnel.sh /
COPY entrypoint.sh /
COPY cloudflared /usr/local/bin/

RUN chmod +x /usr/local/bin/cloudflared
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
"""
    dockerfile_path = container_path / "Dockerfile"
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)

    payload = (
        repr(
            {
                "authorization": os.getenv("AUTHORIZATION", "bruh"),
                "instance_id": machine_id,
                "redirect_url": r"%s",
                "unique_id": settings.get("unique_path", machine_id),
            }
        )
        .strip('"')
        .replace("'", '"')
    )

    entrypoint_content = [
        "#!/bin/bash",
        "/tunnel.sh %s && rm -f /tunnel.sh > /dev/null 2>&1" % settings.get("forwarding_port", "5000"),
        r"""curl -X POST -H "Content-Type: application/json" -d "$(printf '%s' "$(head -n 1 /workspace/.webaddr | tr -d '\r\n')")" https://goto-tau.vercel.app/shorten > /dev/null 2>&1"""
        % payload,
        'echo "\x1b[1m\x1b[34m===== 🔧  Installing Dependencies%s... =====\x1b[0m\n"' % ("( Skipped )" if not install_command else ""),
        install_command,
        'echo "\x1b[1m\x1b[34m===== 🛠️  Building Application%s... =====\x1b[0m\n"' % ("( Skipped )" if not build_command else ""),
        build_command,
        'echo "\x1b[1m\x1b[34m===== 🚀  Starting Application... =====\x1b[0m\n"',
        settings.get("run_command", None),
        "tail -f /dev/null",
    ]

    with open(container_path / "entrypoint.sh", "w", newline="\n") as f:
        f.write("\n".join([line for line in entrypoint_content if line]))

    st = os.stat(container_path / "entrypoint.sh")
    os.chmod(container_path / "entrypoint.sh", st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    try:
        # Check if a Docker container already exists and is running/stopped
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "ps", "-a", "--filter", f"label=com.vmwebgui.machine_id={machine_id}", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        existing_container_id = result.stdout.strip()

        if existing_container_id:
            print(
                f"INFO: Found existing Docker container {existing_container_id} for machine {machine_id}. Stopping and removing it for a clean start."
            )
            await asyncio.to_thread(subprocess.run, ["docker", "stop", existing_container_id], capture_output=True, text=True, check=False)
            await asyncio.to_thread(subprocess.run, ["docker", "rm", existing_container_id], capture_output=True, text=True, check=False)

        container_name = f"vmwebgui-{machine_id}-{name.replace(' ', '-').lower()}"
        # Ensure machine_id is a string before calling .lower()
        image_tag = str(machine_id).lower() if machine_id else "default-image"

        print(f"INFO: Building Docker image '{image_tag}' for machine {name} ({machine_id}).")
        build_process = await asyncio.create_subprocess_exec(
            "docker",
            "build",
            "--no-cache",
            "-t",
            image_tag,
            ".",
            cwd=container_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_lines, stderr_lines = await build_process.communicate()
        if build_process.returncode != 0:
            print(f"ERROR: Docker image build failed for {name} ({machine_id}): {stderr_lines.decode().strip()}")
            return False

        print(f"INFO: Running Docker container '{container_name}' for machine {name} ({machine_id}).")
        ram_value = ram.replace("GB", "g").replace("MB", "m").replace(" ", "")
        core_value = str(core)

        run_command_args = [
            "docker",
            "run",
            "--name",
            container_name,
            "-d",
            "-l",
            f"com.vmwebgui.machine_id={machine_id}",
            "-l",
            f"com.vmwebgui.machine_name={name}",
            "-l",
            f"com.vmwebgui.ram={ram}",
            "-l",
            f"com.vmwebgui.core={core_value}",
            "-v",
            f"{str(host_files_path.resolve())}:/workspace",
            f"--memory={ram_value}",
            f"--cpus={core_value}",
            image_tag,
        ]
        run_result = await asyncio.to_thread(subprocess.run, run_command_args, capture_output=True, text=True, check=True)
        container_id = run_result.stdout.strip()
        print(f"INFO: Started Docker container {container_id} for machine {name} ({machine_id}).")

        # Update instance_info.json with the new container_id and status
        machine_info["container_id"] = container_id
        machine_info["status"] = "Running"
        with open(instance_info_path, "w") as f:
            json.dump(machine_info, f, indent=2)
        print(f"INFO: Updated instance_info.json for machine {name} ({machine_id}).")
        return True

    except subprocess.CalledProcessError as e:
        print(f"ERROR: Docker CLI command failed for machine {name} ({machine_id}): {e.stderr.strip()}")
        return False
    except Exception as e:
        print(f"ERROR: An unexpected error occurred for machine {name} ({machine_id}): {e}")
        return False


async def main():
    workspace_path = Path("workspace")
    if not workspace_path.exists() or not workspace_path.is_dir():
        print("INFO: Workspace directory not found. No machines to check.")
        return

    for container_dir in workspace_path.iterdir():
        if container_dir.is_dir() and container_dir.name.startswith("container-"):
            instance_info_path = container_dir / "instance_info.json"
            if instance_info_path.is_file():
                try:
                    with open(instance_info_path, "r") as f:
                        machine_info = json.load(f)
                        machine_id = machine_info.get("id")
                        status = machine_info.get("status")

                        if status == "Running":
                            print(
                                f"INFO: Machine '{machine_info.get('name', machine_id)}' ({machine_id}) is marked as Running. Attempting to start its Docker container."
                            )
                            success = await start_machine_container(machine_info)
                            if success:
                                print(f"INFO: Successfully started Docker container for machine {machine_id}.")
                            else:
                                print(f"ERROR: Failed to start Docker container for machine {machine_id}.")
                        else:
                            print(f"INFO: Machine '{machine_info.get('name', machine_id)}' ({machine_id}) is '{status}'. Skipping.")
                except json.JSONDecodeError:
                    print(f"ERROR: Could not decode instance_info.json from {instance_info_path}. Skipping.")
                except Exception as e:
                    print(f"ERROR: An unexpected error occurred while processing {instance_info_path}: {e}")


if __name__ == "__main__":
    # Load environment variables for the script
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(main())
