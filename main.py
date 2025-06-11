from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import shutil
import os
import subprocess
import asyncio  # Import asyncio for asynchronous operations
from pydantic import BaseModel
import uuid  # Import uuid for generating unique IDs
import datetime  # Import datetime for uptime calculation
import requests  # Import requests for HTTP requests
from typing import cast
import stat
import traceback  # Import traceback for detailed error logging
import zipfile  # Import zipfile for handling zip archives
from starlette.middleware.sessions import SessionMiddleware
from fastapi import Depends, status, Response
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define activity log file path
ACTIVITY_LOG_FILE = Path("activity.log")

# Retrieve credentials from environment variables
USERS_DB = {os.getenv("VM_WEB_GUI_USERNAME", None): os.getenv("VM_WEB_GUI_PASSWORD", None)}
SECRET_KEY = os.getenv("VM_WEB_GUI_SECRET_KEY", "your-super-secret-key")

# You can generate a secret key using:
# import os
# os.urandom(32).hex()


def log_activity(message: str):
    """Appends a timestamped message to the activity log file, capping it at 100 entries."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    try:
        # Read existing logs
        if ACTIVITY_LOG_FILE.is_file():
            with open(ACTIVITY_LOG_FILE, "r") as f:
                lines = f.readlines()
        else:
            lines = []

        # If more than 99 lines, remove the oldest ones (from the beginning)
        if len(lines) >= 100:
            lines = lines[len(lines) - 99 :]  # Keep only the last 99 lines

        # Add the new log entry
        lines.append(log_entry)

        # Write all lines back to the file
        with open(ACTIVITY_LOG_FILE, "w") as f:
            f.writelines(lines)

    except Exception as e:
        print(f"ERROR: Failed to write to activity log file: {e}")


# Dictionary to store active log processes, mapping machine_id to subprocess.Popen object
active_log_processes: dict[str, subprocess.Popen] = {}
# Lock to protect active_log_processes from concurrent access
log_process_lock = asyncio.Lock()

# In-memory store for historical usage data
# Structure: {machine_id: [{timestamp: str, cpu_percent: str, mem_usage: str, mem_limit: str, net_rx: str, net_tx: str}, ...]}
historical_usage_data: dict[str, list[dict]] = {}
MAX_HISTORY_POINTS = 100 # Keep last 100 data points for history


# Define a Pydantic model for the Git clone request body
class GitCloneRequest(BaseModel):
    repo_url: str


# Define a Pydantic model for machine settings
class MachineSettings(BaseModel):
    build_command: str = ""
    install_command: str = ""
    run_command: str = ""
    forwarding_port: str = ""
    unique_path: str = ""


class UserLogin(BaseModel):
    username: str
    password: str


app = FastAPI()

# Add SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Mount static files for the dashboard
app.mount("/dashboard", StaticFiles(directory="vercel_dashboard", html=True), name="dashboard")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_root(request: Request):
    if not request.session.get("authenticated"):
        return FileResponse("vercel_dashboard/login.html")
    return FileResponse("vercel_dashboard/index.html")


def authenticate_user(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return True


@app.post("/login")
async def login(user: UserLogin, request: Request):
    username = user.username
    password = user.password

    if username in USERS_DB and USERS_DB[username] == password:
        request.session["authenticated"] = True
        log_activity(f"User '{username}' logged in successfully.")
        return {"message": "Login successful"}
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


@app.post("/logout")
async def logout(request: Request):
    request.session.pop("authenticated", None)
    log_activity("User logged out.")
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@app.get("/machines", dependencies=[Depends(authenticate_user)])
async def get_machines():
    workspace_path = Path("workspace")
    machines_data = []

    if not workspace_path.exists() or not workspace_path.is_dir():
        # If workspace doesn't exist, return empty list rather than 404
        return []

    for container_dir in workspace_path.iterdir():
        if container_dir.is_dir() and container_dir.name.startswith("container-"):
            instance_info_path = container_dir / "instance_info.json"
            if instance_info_path.is_file():
                try:
                    with open(instance_info_path, "r") as f:
                        machine_info = json.load(f)
                        machine_id = machine_info.get("id")

                        # Preserve "Starting" or "Stopping" status from instance_info.json if set
                        # This ensures the frontend correctly displays transient states even if Docker's status is not immediately updated or is empty.
                        current_persisted_status = machine_info.get("status")
                        if current_persisted_status in ["Starting", "Stopping"]:
                            # If the persisted status is "Starting" or "Stopping", use it directly
                            # and skip querying Docker for status, as Docker's output might be inconsistent
                            # during these brief transition periods.
                            pass  # No change needed, machine_info already has the correct status
                        else:
                            # If not in a transient state, then query Docker for the actual status
                            machine_info["status"] = "Unknown"  # Default before Docker check
                            machine_info["uptime"] = "N/A"
                            machine_info["docker_image"] = machine_info.get("docker_image", "N/A")
                            machine_info["container_id"] = None

                            # Use docker CLI to find existing container by label
                            try:
                                result = await asyncio.to_thread(
                                    subprocess.run,
                                    [
                                        "docker",
                                        "ps",
                                        "-a",
                                        "--filter",
                                        f"label=com.vmwebgui.machine_id={machine_id}",
                                        "--format",
                                        "{{.ID}}\t{{.Status}}\t{{.Image}}\t{{.CreatedAt}}",
                                    ],
                                    capture_output=True,
                                    text=True,
                                    check=False,
                                )
                                if result.stdout.strip():
                                    parts = result.stdout.strip().split("\t")
                                    container_id_from_docker = parts[0]
                                    status_from_docker = parts[1]
                                    image_from_docker = parts[2]
                                    created_at_str = parts[3]

                                    # Determine simplified status based on Docker's output
                                    if status_from_docker.startswith("Up"):
                                        machine_info["status"] = "Running"
                                    elif status_from_docker.startswith("Exited"):
                                        machine_info["status"] = "Stopped"
                                    elif status_from_docker.startswith("Created") or status_from_docker.startswith("Restarting"):
                                        machine_info["status"] = "Starting"
                                    elif status_from_docker.startswith("Stopping"):
                                        machine_info["status"] = "Stopping"
                                    else:
                                        machine_info["status"] = "Unknown"  # Fallback for other statuses

                                    # Use image_from_docker for the actual Docker image
                                    machine_info["docker_image"] = image_from_docker
                                    machine_info["container_id"] = container_id_from_docker  # Corrected variable name

                                    # Sanitize docker_image for frontend display (extract base name)
                                    display_image_name = image_from_docker.split(":")[0].lower()
                                    # If the display_image_name is a UUID-like string (e.g., a machine ID), default it
                                    if len(display_image_name) == 12 and all(c.isalnum() or c == "-" for c in display_image_name):
                                        machine_info["docker_image"] = "default"
                                    else:
                                        machine_info["docker_image"] = display_image_name

                                    # Calculate uptime
                                    created_at = None
                                    # Attempt 1: Parse "YYYY-MM-DD HH:MM:SS +ZZZZ TZ_ABBR"
                                    try:
                                        parts = created_at_str.split(" ")
                                        # Check if it has at least 4 parts (date, time, offset, abbr)
                                        # and if the third part (index 2) starts with '+' or '-'
                                        if len(parts) >= 4 and (parts[2].startswith("+") or parts[2].startswith("-")):
                                            # Reconstruct string without the last part (timezone abbreviation)
                                            cleaned_str = " ".join(parts[0:3])  # Take date, time, and offset
                                            created_at = datetime.datetime.strptime(cleaned_str, "%Y-%m-%d %H:%M:%S %z")
                                    except ValueError:
                                        pass  # Continue to next attempt if this fails

                                    # Attempt 2: Parse ISO format (e.g., "YYYY-MM-DDTHH:MM:SS.fffffffffZ")
                                    if created_at is None:
                                        try:
                                            created_at = datetime.datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                                        except ValueError:
                                            pass  # Continue to fallback if this fails

                                    # Fallback if no format matches
                                    if created_at is None:
                                        print(
                                            f"WARNING: Could not parse Docker CreatedAt string: '{created_at_str}'. Defaulting to current time."
                                        )
                                        created_at = datetime.datetime.now(datetime.timezone.utc)

                                    now = datetime.datetime.now(datetime.timezone.utc)
                                    uptime_delta = now - created_at
                                    total_seconds = int(uptime_delta.total_seconds())
                                    hours = total_seconds // 3600
                                    minutes = (total_seconds % 3600) // 60
                                    seconds = total_seconds % 60
                                    machine_info["uptime"] = f"{hours}h {minutes}m {seconds}s"
                                else:
                                    machine_info["status"] = "Stopped"  # Container not found in Docker
                            except Exception as docker_e:
                                print(f"Error querying Docker for machine {machine_id}: {docker_e}")
                                machine_info["status"] = "Docker Error"  # Indicate Docker issue

                        machines_data.append(machine_info)
                except json.JSONDecodeError:
                    print(f"Error decoding JSON from {instance_info_path}")
                except Exception as e:
                    print(f"Error reading {instance_info_path}: {e}")
    return machines_data


@app.post("/machines/create", dependencies=[Depends(authenticate_user)])
async def create_machine(machine_data: dict):
    name = machine_data.get("name")
    ram = machine_data.get("ram")
    core = machine_data.get("core")
    docker_image = machine_data.get("docker_image")  # Still capture for future use

    if name is None or ram is None or core is None or docker_image is None:
        raise HTTPException(status_code=400, detail="Missing required fields")

    try:
        ram = int(ram)
        core = int(core)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="RAM and Core must be valid numbers")

    if not (1 <= ram <= 8):
        raise HTTPException(status_code=400, detail="RAM must be between 1 and 8 GB")
    if not (1 <= core <= 4):
        raise HTTPException(status_code=400, detail="Core must be between 1 and 4")

    instance_id = str(uuid.uuid4())[:12]
    container_dir_name = f"container-{instance_id}"
    container_path = Path("workspace") / container_dir_name
    files_path = container_path / "files"

    try:
        container_path.mkdir(parents=True, exist_ok=True)
        files_path.mkdir(parents=True, exist_ok=True)  # Ensure files directory exists

        new_machine_info = {
            "id": instance_id,
            "name": name,
            "ram": f"{ram}GB",
            "core": core,
            "storage": "N/A",
            "status": "Stopped",  # Initially stopped, Docker not involved yet
            "uptime": "0d 0h 0m",
            "docker_image": docker_image,  # Store image for later Docker creation
            "container_id": None,  # No Docker container yet
            "settings": {
                "build_command": "",
                "install_command": "",
                "run_command": "",
                "forwarding_port": "5000",
                "unique_path": instance_id,
            },  # Default settings
        }

        instance_info_path = container_path / "instance_info.json"

        with open(instance_info_path, "w") as f:
            json.dump(new_machine_info, f, indent=2)

        log_activity(f"Machine '{name}' ({instance_id}) created.")
        shutil.copy("cloudflared", container_path / "cloudflared")
        shutil.copy("tunnel.sh", container_path / "tunnel.sh")

        return {"message": "Machine created successfully", "machine": new_machine_info}

    except Exception as e:
        print(f"ERROR: Error creating machine directory or info file: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating machine: {e}")


@app.delete("/machines/delete/{machine_id}", dependencies=[Depends(authenticate_user)])
async def delete_machine(machine_id: str):
    # Always attempt to remove the host directory first
    container_dir_name = f"container-{machine_id}"
    host_container_path = Path("workspace") / container_dir_name
    instance_info_path = host_container_path / "instance_info.json"
    machine_name = machine_id  # Default name if info file is gone

    # Try to get machine name before deletion
    if instance_info_path.is_file():
        try:
            with open(instance_info_path, "r") as f:
                machine_info = json.load(f)
                machine_name = machine_info.get("name", machine_id)
        except json.JSONDecodeError:
            print(f"WARNING: Could not decode instance_info.json for {machine_id} during deletion.")
        except Exception as e:
            print(f"WARNING: Error reading instance_info.json for {machine_id} during deletion: {e}")

    if host_container_path.exists():
        try:
            shutil.rmtree(host_container_path)
            print(f"INFO: Removed host directory {host_container_path}")
        except OSError as e:
            print(f"ERROR: Failed to remove host directory {host_container_path}: {e}")
            raise HTTPException(status_code=500, detail=f"Error deleting machine directory on host: {e}")
    else:
        print(f"WARNING: Host directory {host_container_path} not found for machine {machine_id}. Proceeding to check Docker.")

    # Now, attempt to remove the Docker container if it exists
    try:
        # Find container ID by label
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "ps", "-a", "--filter", f"label=com.vmwebgui.machine_id={machine_id}", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        container_id = result.stdout.strip()

        if container_id:
            print(f"INFO: Found Docker container {container_id} for machine {machine_id}. Attempting to stop and remove.")
            await asyncio.to_thread(
                subprocess.run, ["docker", "stop", container_id], capture_output=True, text=True, check=False
            )  # Stop, but don't fail if already stopped
            await asyncio.to_thread(
                subprocess.run, ["docker", "rm", container_id], capture_output=True, text=True, check=False
            )  # Remove, but don't fail if already removed
            print(f"INFO: Stopped and removed Docker container {container_id}.")
        else:
            print(f"INFO: No Docker container found for machine ID {machine_id}. Host directory already handled.")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Docker CLI error during deletion of machine {machine_id}: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"Docker CLI error during deletion: {e.stderr.strip()}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during Docker deletion for machine {machine_id}: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during Docker deletion: {e}")

    log_activity(f"Machine '{machine_name}' ({machine_id}) deleted.")
    return {"message": f"Machine {machine_id} deleted successfully"}


@app.post("/machines/{machine_id}/start", dependencies=[Depends(authenticate_user)])
async def start_machine(machine_id: str):
    container_dir_name = f"container-{machine_id}"
    container_path = Path("workspace") / container_dir_name
    instance_info_path = container_path / "instance_info.json"
    host_files_path = container_path / "files"
    instance_info = json.load(open(instance_info_path, "r"))
    settings = instance_info["settings"]

    install_command = settings.get("install_command", "")
    build_command = settings.get("build_command", "")
    run_command_setting = settings.get("run_command", "")  # Renamed to avoid conflict with run_command_args

    dockerfile_content = (
        r"""FROM %s

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
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
        % instance_info["docker_image"]
    )

    dockerfile_path = container_path / "Dockerfile"

    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)

    payload = (
        repr(
            {
                "authorization": os.getenv("AUTHORIZATION", "bruhu"),
                "instance_id": instance_info["id"],
                "redirect_url": r"%s",
                "unique_id": instance_info["settings"]["unique_path"],
            }
        )
        .strip('"')
        .replace("'", '"')
    )

    entrypoint_content = [
        "#!/bin/bash",
        "/tunnel.sh %s && rm -f /tunnel.sh > /dev/null 2>&1" % instance_info["settings"]["forwarding_port"],
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

    if not instance_info_path.is_file():
        raise HTTPException(status_code=404, detail=f"Machine with ID {machine_id} not found.")

    try:
        with open(instance_info_path, "r+") as f:
            machine_info = json.load(f)
            # Set status to "Starting" immediately
            machine_info["status"] = "Starting"
            f.seek(0)
            json.dump(machine_info, f, indent=2)
            f.truncate()
            log_activity(f"Machine '{machine_info.get('name', machine_id)}' ({machine_id}) status set to Starting.")

            # Check if a Docker container already exists and is running/stopped
            try:
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
                    await asyncio.to_thread(
                        subprocess.run, ["docker", "stop", existing_container_id], capture_output=True, text=True, check=False
                    )
                    await asyncio.to_thread(
                        subprocess.run, ["docker", "rm", existing_container_id], capture_output=True, text=True, check=False
                    )
            except Exception as e:
                print(f"WARNING: Error checking/removing existing container: {e}")

            name = machine_info.get("name", f"machine-{machine_id}")
            docker_image = machine_info.get("docker_image")
            ram = machine_info.get("ram", "N/A")
            core = machine_info.get("core", "N/A")
            settings = machine_info.get("settings", {})

            if not docker_image:
                raise HTTPException(status_code=400, detail="Docker image not specified in machine settings.")

            container_name = f"vmwebgui-{machine_id}-{name.replace(' ', '-').lower()}"

            # Build the Docker image asynchronously
            image_tag = machine_id.lower()  # Use machine_id as the image tag
            print(f"INFO: Building Docker image '{image_tag}' from Dockerfile in {container_path}.")

            # Use asyncio.create_subprocess_exec for non-blocking process execution
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

            stdout_lines = []
            stderr_lines = []

            # Asynchronously read stdout and stderr
            async def read_stream(stream, buffer):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded_line = line.decode().strip()
                    buffer.append(decoded_line)
                    print(f"BUILD LOG (Dockerfile): {decoded_line}")

            await asyncio.gather(read_stream(build_process.stdout, stdout_lines), read_stream(build_process.stderr, stderr_lines))

            returncode = await build_process.wait()

            if returncode != 0:
                error_output = "\n".join(stderr_lines) if stderr_lines else "No specific error output."
                raise HTTPException(status_code=500, detail=f"Docker image build failed (exit code {returncode}): {error_output}")
            print(f"INFO: Docker image '{image_tag}' built successfully.")

            # Run the Docker container
            print(f"INFO: Running Docker container '{container_name}' from image '{image_tag}'.")

            ram_value = machine_info["ram"].replace("GB", "g").replace("MB", "m").replace(" ", "")
            core_value = str(machine_info["core"])

            run_command_args = [
                "docker",
                "run",
                "--name",
                container_name,
                "-d",  # Detached mode
                "-l",
                f"com.vmwebgui.machine_id={machine_id}",
                "-l",
                f"com.vmwebgui.machine_name={name}",
                "-l",
                f"com.vmwebgui.ram={ram}",
                "-l",
                f"com.vmwebgui.core={str(core)}",
                "-v",
                f"{str(host_files_path.resolve())}:/workspace",  # Changed from /app/files to /workspace
                f"--memory={ram_value}",  # Added memory limit
                f"--cpus={core_value}",  # Added cpu limit
                image_tag.lower(),  # Changed image_tag to machine_id.lower()
            ]

            run_result = await asyncio.to_thread(subprocess.run, run_command_args, capture_output=True, text=True, check=True)
            container_id = run_result.stdout.strip()  # Docker run outputs container ID on success
            print(f"INFO: Started Docker container {container_id} for machine {machine_id}")

            # Get commands from settings

            print(
                f"DEBUG: Machine {machine_id} settings - Install: '{install_command}', Build: '{build_command}', Run: '{run_command_setting}'"
            )

            # Update machine info with new Docker details
            # Get current status and image from docker inspect
            inspect_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "inspect", "--format", "{{.State.Status}}\t{{.Config.Image}}", container_id],
                capture_output=True,
                text=True,
                check=True,
            )
            status_from_docker, image_from_docker = inspect_result.stdout.strip().split("\t")

            machine_info["status"] = status_from_docker.capitalize()
            machine_info["container_id"] = container_id

            # Save updated info
            f.seek(0)
            json.dump(machine_info, f, indent=2)
            f.truncate()

            log_activity(f"Machine '{name}' ({machine_id}) started.")
            return {"message": f"Machine {machine_id} started successfully.", "machine": machine_info}

    except subprocess.CalledProcessError as e:
        print(f"ERROR: Docker CLI command failed during machine start: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"Docker CLI error during machine start: {e.stderr.strip()}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during machine start: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during machine start: {e}")


@app.post("/machines/{machine_id}/stop", dependencies=[Depends(authenticate_user)])
async def stop_machine(machine_id: str):
    container_dir_name = f"container-{machine_id}"
    instance_info_path = Path("workspace") / container_dir_name / "instance_info.json"

    if not instance_info_path.is_file():
        raise HTTPException(status_code=404, detail=f"Machine with ID {machine_id} not found.")

    try:
        with open(instance_info_path, "r+") as f:
            machine_info = json.load(f)

            machine_info["status"] = "Stopping"
            f.seek(0)
            json.dump(machine_info, f, indent=2)
            f.truncate()
            log_activity(f"Machine '{machine_info.get('name', machine_id)}' ({machine_id}) status set to Stopping.")

            container_id = machine_info.get("container_id")

            if not container_id:
                raise HTTPException(status_code=400, detail="Machine is not running or container ID is unknown.")

            try:
                # Check if container is running before attempting to stop
                inspect_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                current_status = inspect_result.stdout.strip().lower()

                if current_status == "running":
                    await asyncio.to_thread(subprocess.run, ["docker", "stop", container_id], capture_output=True, text=True, check=True)
                    print(f"INFO: Stopped Docker container {container_id} for machine {machine_id}")
                    machine_info["status"] = "Stopped"
                    machine_info["uptime"] = "0d 0h 0m"  # Reset uptime on stop
                    machine_info["container_id"] = None  # Clear container ID
                else:
                    print(f"INFO: Docker container {container_id} for machine {machine_id} is already {current_status}. No action needed.")
                    machine_info["status"] = current_status.capitalize()  # Update status in info if it changed externally
                    machine_info["uptime"] = "0d 0h 0m"  # Ensure uptime is reset if it was stopped externally
                    machine_info["container_id"] = None  # Clear container ID if it's not running

                # Save updated info
                f.seek(0)
                json.dump(machine_info, f, indent=2)
                f.truncate()

                machine_name = machine_info.get("name", machine_id)
                log_activity(f"Machine '{machine_name}' ({machine_id}) stopped.")
                return {"message": f"Machine {machine_id} stopped successfully.", "machine": machine_info}
            except subprocess.CalledProcessError as e:
                print(f"ERROR: Docker CLI error during machine stop: {e.stderr}")
                raise HTTPException(status_code=500, detail=f"Docker CLI error during machine stop: {e.stderr.strip()}")
            except Exception as e:
                print(f"ERROR: An unexpected error occurred during machine stop: {e}")
                raise HTTPException(status_code=500, detail=f"An unexpected error occurred during machine stop: {e}")

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Error decoding machine info JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading machine info for stop: {e}")


@app.get("/machines/{machine_id}/settings", dependencies=[Depends(authenticate_user)])
async def get_machine_settings(machine_id: str):
    container_dir_name = f"container-{machine_id}"
    container_path = Path("workspace") / container_dir_name
    instance_info_path = container_path / "instance_info.json"

    if not instance_info_path.is_file():
        raise HTTPException(status_code=404, detail=f"Machine with ID {machine_id} not found.")

    try:
        with open(instance_info_path, "r") as f:
            machine_info = json.load(f)
            settings = machine_info.get("settings", {})
            # Ensure unique_path is always present, defaulting to machine_id if not set
            if not settings.get("unique_path"):
                settings["unique_path"] = machine_id
            return MachineSettings(**settings)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Error decoding machine info JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading machine settings: {e}")


@app.put("/machines/{machine_id}/settings", dependencies=[Depends(authenticate_user)])
async def update_machine_settings(machine_id: str, settings: MachineSettings):
    container_dir_name = f"container-{machine_id}"
    container_path = Path("workspace") / container_dir_name
    instance_info_path = container_path / "instance_info.json"

    if not instance_info_path.is_file():
        raise HTTPException(status_code=404, detail=f"Machine with ID {machine_id} not found.")

    try:
        # Validate forwarding_port
        forwarding_port_str = settings.forwarding_port
        if forwarding_port_str:  # Only validate if not empty
            try:
                port = int(forwarding_port_str)
                if not (1 <= port <= 65535):
                    raise HTTPException(status_code=400, detail="Forwarding Port must be between 1 and 65535.")
            except ValueError:
                raise HTTPException(status_code=400, detail="Forwarding Port must be a valid integer.")

        with open(instance_info_path, "r+") as f:
            machine_info = json.load(f)
            machine_info["settings"] = settings.dict()  # Update the settings
            f.seek(0)  # Rewind to the beginning of the file
            json.dump(machine_info, f, indent=2)
            f.truncate()  # Truncate any remaining old content

        log_activity(f"Machine {machine_id}: Settings updated.")
        return {"message": f"Settings for machine {machine_id} updated successfully."}
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Error decoding machine info JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating machine settings: {e}")


@app.get("/machines/{machine_id}/logs", dependencies=[Depends(authenticate_user)])
async def get_machine_logs(machine_id: str, request: Request):
    container_dir_name = f"container-{machine_id}"
    instance_info_path = Path("workspace") / container_dir_name / "instance_info.json"

    if not instance_info_path.is_file():
        raise HTTPException(status_code=404, detail=f"Machine with ID {machine_id} not found.")

    try:
        with open(instance_info_path, "r") as f:
            machine_info = json.load(f)
            container_id = machine_info.get("container_id")

        if not container_id:
            return PlainTextResponse("Machine not started, no Docker logs available. Start the machine first.")

        async def generate_logs():
            logs_process = None
            try:
                # Check if container exists and is running (outside the lock, as it's a read-only operation)
                inspect_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                current_status = inspect_result.stdout.strip().lower()

                if not inspect_result.stdout.strip() or "no such object" in inspect_result.stderr.lower():
                    yield f"Docker container with ID {container_id} not found. It might have been removed manually. Logs unavailable.\n"
                    return
                elif current_status != "running":
                    yield f"Docker container is {current_status}. Logs unavailable. Start the machine to view live logs.\n"
                    return

                # Fetch live Docker container logs using subprocess.Popen and asyncio.to_thread
                logs_process = subprocess.Popen(
                    ["docker", "logs", "--tail", "500", "-f", container_id],  # Added --tail 1000
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

                # Stream stdout
                assert logs_process.stdout is not None
                while True:
                    # Check for client disconnection
                    if await request.is_disconnected():
                        print(f"INFO: Client disconnected from logs for machine {machine_id}. Terminating log process.")
                        break

                    line = await asyncio.to_thread(logs_process.stdout.readline)
                    if not line:
                        if logs_process.poll() is not None:
                            break
                        await asyncio.sleep(0.1)
                        continue

                    decoded_line = line.strip()
                    print(f"LIVE LOG: {decoded_line}")
                    yield decoded_line + "\n"
                    await asyncio.sleep(0.01)

                # Read any remaining stderr if the process exited
                # assert logs_process.stderr is not None
                # stderr_output = (await asyncio.to_thread(logs_process.stderr.read)).strip()
                # if stderr_output:
                #     print(f"LIVE LOG (ERR): {stderr_output}")
                #     yield f"LIVE LOG (ERR): {stderr_output}\n"

                await asyncio.to_thread(logs_process.wait)
                if logs_process.returncode != 0:
                    assert logs_process.stderr is not None
                    stderr_output = (await asyncio.to_thread(logs_process.stderr.read)).strip()
                    error_message = (
                        f"Docker CLI error fetching logs for container {container_id} (exit code {logs_process.returncode}): {stderr_output}\n"
                    )
                    print(f"ERROR: {error_message}")
                    yield error_message
                yield "\n--- END LIVE CONTAINER LOGS ---\n"

            except Exception as e:
                error_message = f"An unexpected error occurred fetching logs for container {container_id}: {e}\n"
                detailed_error = traceback.format_exc()
                print(f"ERROR: {error_message}\n{detailed_error}")
                yield f"{error_message}\n{detailed_error}\n"
            finally:
                # Ensure the subprocess is terminated
                if logs_process and logs_process.poll() is None:
                    print(f"INFO: Ensuring log process for machine {machine_id} is terminated in finally block.")
                    try:
                        logs_process.terminate()
                        await asyncio.to_thread(logs_process.wait, timeout=1)
                    except subprocess.TimeoutExpired:
                        logs_process.kill()
                        await asyncio.to_thread(logs_process.wait)
                    except Exception as e:
                        print(f"WARNING: Error during final termination of log process for {machine_id}: {e}")

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Error decoding machine info JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading machine info for logs endpoint: {e}")

    return StreamingResponse(generate_logs(), media_type="text/plain")


@app.get("/machines/{machine_id}/usage-snapshot", dependencies=[Depends(authenticate_user)])
async def get_machine_usage_snapshot(machine_id: str):
    container_dir_name = f"container-{machine_id}"
    instance_info_path = Path("workspace") / container_dir_name / "instance_info.json"

    if not instance_info_path.is_file():
        raise HTTPException(status_code=404, detail=f"Machine with ID {machine_id} not found.")

    try:
        with open(instance_info_path, "r") as f:
            machine_info = json.load(f)
            container_id = machine_info.get("container_id")

        if not container_id:
            return {"error": "Machine not started, no Docker usage data available. Start the machine first."}

        # Check if container exists and is running
        inspect_result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
            capture_output=True,
            text=True,
            check=False,
        )
        current_status = inspect_result.stdout.strip().lower()

        if not inspect_result.stdout.strip() or "no such object" in inspect_result.stderr.lower():
            return {"error": f"Docker container with ID {container_id} not found. It might have been removed manually. Usage data unavailable."}
        elif current_status != "running":
            return {"error": f"Docker container is {current_status}. Usage data unavailable. Start the machine to view live usage."}

        try:
            # Fetch Docker container stats using subprocess.run with --no-stream
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}", container_id],
                capture_output=True,
                text=True,
                check=True, # Check for non-zero exit code
            )

            line = result.stdout.strip()
            if line:
                parts = line.split("\t")
                if len(parts) == 3:
                    cpu_percent = parts[0]
                    mem_usage_raw = parts[1]
                    net_io_raw = parts[2]

                    mem_parts = mem_usage_raw.split(" / ")
                    mem_usage = mem_parts[0] if len(mem_parts) > 0 else "N/A"
                    mem_limit = mem_parts[1] if len(mem_parts) > 1 else "N/A"

                    net_parts = net_io_raw.split(" / ")
                    net_rx = net_parts[0] if len(net_parts) > 0 else "N/A"
                    net_tx = net_parts[1] if len(net_parts) > 1 else "N/A"

                    usage_data = {
                        "cpu_percent": cpu_percent,
                        "mem_usage": mem_usage,
                        "mem_limit": mem_limit,
                        "net_rx": net_rx,
                        "net_tx": net_tx,
                    }
                    # Store the snapshot in historical data
                    timestamp = datetime.datetime.now().isoformat()
                    current_snapshot = {
                        "timestamp": timestamp,
                        "cpu_percent": cpu_percent,
                        "mem_usage": mem_usage,
                        "mem_limit": mem_limit,
                        "net_rx": net_rx,
                        "net_tx": net_tx,
                    }

                    if machine_id not in historical_usage_data:
                        historical_usage_data[machine_id] = []

                    historical_usage_data[machine_id].append(current_snapshot)
                    # Trim history to MAX_HISTORY_POINTS
                    if len(historical_usage_data[machine_id]) > MAX_HISTORY_POINTS:
                        historical_usage_data[machine_id] = historical_usage_data[machine_id][-MAX_HISTORY_POINTS:]

                    return usage_data
                else:
                    return {"error": "Failed to parse docker stats output"}
            else:
                return {"error": "No output from docker stats"}

        except subprocess.CalledProcessError as e:
            error_message = f"Docker CLI error fetching usage for container {container_id} (exit code {e.returncode}): {e.stderr.strip()}"
            print(f"ERROR: {error_message}")
            return {"error": error_message}
        except Exception as e:
            error_message = f"An unexpected error occurred fetching usage for container {container_id}: {e}"
            detailed_error = traceback.format_exc()
            print(f"ERROR: {error_message}\n{detailed_error}")
            return {"error": error_message}

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Error decoding machine info JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading machine info for usage endpoint: {e}")


@app.get("/machines/{machine_id}/usage-history", dependencies=[Depends(authenticate_user)])
async def get_machine_usage_history(machine_id: str):
    """Returns historical usage data for a given machine."""
    if machine_id not in historical_usage_data:
        return []
    return historical_usage_data[machine_id]


@app.get("/machines/{machine_id}/files", dependencies=[Depends(authenticate_user)])
async def get_machine_files(machine_id: str, path: str = "/"):
    # Construct the absolute path directly from the current working directory
    base_dir_absolute = Path.cwd() / "workspace" / f"container-{machine_id}" / "files"

    # Ensure the base directory for machine files exists
    if not base_dir_absolute.exists():
        raise HTTPException(status_code=404, detail=f"Machine files directory not found for ID {machine_id}.")

    # Use base_dir_absolute directly, avoiding resolve() on potentially problematic paths
    base_dir = base_dir_absolute
    clean_path: str = cast(str, path.strip("/"))
    target_dir = base_dir.joinpath(clean_path)

    print(f"DEBUG: base_dir: {base_dir}")
    print(f"DEBUG: clean_path: '{clean_path}'")
    print(f"DEBUG: target_dir: {target_dir}")
    print(f"DEBUG: base_dir.exists(): {base_dir.exists()}")
    print(f"DEBUG: target_dir.exists(): {target_dir.exists()}")
    print(f"DEBUG: target_dir.is_dir(): {target_dir.is_dir()}")

    # Ensure the target directory is within the base_dir for security
    try:
        if not target_dir.is_relative_to(base_dir):
            print(f"SECURITY ALERT: Path {target_dir} is NOT relative to {base_dir}")
            raise HTTPException(status_code=400, detail="Invalid path: Not relative to base directory")
    except ValueError as e:
        # This can happen if target_dir and base_dir are on different drives or have no common root
        print(f"SECURITY ALERT: ValueError during is_relative_to check: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")

    # Ensure base_dir exists (it should from create_machine, but as a fallback)
    # This check is now redundant as base_dir_absolute.exists() is already performed
    # if not base_dir.exists():
    #     base_dir.mkdir(parents=True, exist_ok=True)
    #     print(f"DEBUG: Created base_dir: {base_dir}")

    if not target_dir.exists():
        print(f"DEBUG: target_dir does not exist: {target_dir}")
        # Attempt to create the directory if it's the base_dir itself and doesn't exist
        if target_dir == base_dir and not base_dir.exists():
            base_dir.mkdir(parents=True, exist_ok=True)
            print(f"DEBUG: Created missing base_dir: {base_dir}")
        else:
            raise HTTPException(status_code=404, detail="Directory not found")

    if not target_dir.is_dir():
        print(f"DEBUG: target_dir is not a directory: {target_dir}")
        raise HTTPException(status_code=400, detail="Path is not a directory")

    files_list = []
    try:
        for item in target_dir.iterdir():
            if item.is_dir():
                files_list.append({"name": item.name, "type": "folder"})
            elif item.is_file():
                files_list.append({"name": item.name, "type": "file"})

        # Sort the list: folders first, then files, then alphabetically by name
        files_list.sort(key=lambda x: (0 if x["type"] == "folder" else 1, x["name"].lower()))

        print(f"DEBUG: Files found: {[f['name'] for f in files_list]}")
    except Exception as e:
        print(f"ERROR: Failed to list directory contents for {target_dir}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list directory contents: {e}")

    return files_list


@app.post("/machines/{machine_id}/upload", dependencies=[Depends(authenticate_user)])
async def upload_machine_files(machine_id: str, files: list[UploadFile], path: str = Query("/")):  # Changed Form to Query
    base_dir_relative = Path("workspace") / f"container-{machine_id}" / "files"
    base_dir = base_dir_relative.resolve()  # Resolve base_dir to an absolute path
    clean_path: str = cast(str, path.strip("/"))
    target_dir = Path(os.path.join(str(base_dir), clean_path)).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if not target_dir.is_relative_to(base_dir):  # Use the resolved base_dir here
        raise HTTPException(status_code=400, detail="Invalid upload path")

    uploaded_file_names = []
    for file in files:
        if file.filename is None:
            raise HTTPException(status_code=400, detail="Uploaded file is missing a filename.")

        if file.filename.endswith(".zip"):
            # Create a temporary directory to extract the zip file
            temp_zip_path = target_dir / file.filename
            temp_extract_dir = target_dir / f"temp_extract_{uuid.uuid4().hex}"  # Temporary unique directory
            try:
                with open(temp_zip_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

                temp_extract_dir.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                    zip_ref.extractall(temp_extract_dir)

                # Determine the final destination path
                extract_dir_name = file.filename[:-4] if file.filename.endswith(".zip") else file.filename
                final_extract_path = target_dir / extract_dir_name
                final_extract_path.mkdir(parents=True, exist_ok=True)  # Ensure final destination exists

                # Check if the zip file created a single root folder
                extracted_contents = list(temp_extract_dir.iterdir())
                if len(extracted_contents) == 1 and extracted_contents[0].is_dir():
                    # If there's a single directory, move its contents up
                    redundant_root = extracted_contents[0]
                    for item in redundant_root.iterdir():
                        shutil.move(str(item), str(final_extract_path / item.name))
                    shutil.rmtree(redundant_root)  # Remove the now empty redundant root
                else:
                    # Otherwise, move all extracted contents directly
                    for item in extracted_contents:
                        shutil.move(str(item), str(final_extract_path / item.name))

                uploaded_file_names.append(f"{file.filename} (extracted to {extract_dir_name}/)")
                log_activity(f"Machine {machine_id}: Uploaded and extracted '{file.filename}' to '{path}/{extract_dir_name}/'.")
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail=f"Uploaded file {file.filename} is not a valid zip file.")
            except Exception as e:
                # Log the full traceback for debugging
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Could not extract zip file {file.filename}: {e}")
            finally:
                # Clean up the temporary zip file and temporary extraction directory
                if temp_zip_path.exists():
                    os.remove(temp_zip_path)
                if temp_extract_dir.exists():
                    shutil.rmtree(temp_extract_dir)
        else:
            file_path = target_dir / file.filename
            try:
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                uploaded_file_names.append(file.filename)
                log_activity(f"Machine {machine_id}: Uploaded file '{file.filename}' to '{path}'.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Could not upload file {file.filename}: {e}")
            finally:
                file.file.close()
    return {"message": f"Successfully uploaded {', '.join(uploaded_file_names)} to {path}"}


@app.post("/machines/{machine_id}/git-clone", dependencies=[Depends(authenticate_user)])
async def git_clone_repo(machine_id: str, request: GitCloneRequest, path: str = Query("/")):  # Changed Form to Query
    base_dir_relative = Path("workspace") / f"container-{machine_id}" / "files"
    base_dir = base_dir_relative.resolve()  # Resolve base_dir to an absolute path
    clean_path_str = path.strip("/")
    # Ensure clean_path_str is never empty, converting "" to "."
    if clean_path_str:
        final_path_segment = clean_path_str
    else:
        final_path_segment = "."
    target_dir = base_dir / cast(str, final_path_segment)
    target_dir.mkdir(parents=True, exist_ok=True)

    if not target_dir.is_relative_to(base_dir):  # Use the resolved base_dir here
        raise HTTPException(status_code=400, detail="Invalid clone path")

    try:
        # Extract repository name from URL to create a subdirectory
        # Use os.path.basename for robust extraction and ensure it's a string
        repo_name: str = os.path.basename(request.repo_url)
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]  # Remove .git extension

        if not repo_name:  # Ensure repo_name is not empty after processing
            raise HTTPException(status_code=400, detail="Could not determine repository name from URL.")

        # Type assertion to help Pylance understand repo_name is a non-empty string
        # This also acts as a runtime check for unexpected empty strings.
        assert isinstance(repo_name, str) and repo_name, "repo_name must be a non-empty string"

        # Use joinpath for robust path concatenation
        # Ensure repo_name is treated as a non-empty string for type checkers
        final_repo_name: str = cast(str, repo_name)
        clone_target_dir = target_dir / final_repo_name

        # Run git clone command
        # IMPORTANT: In a real application, sanitize repo_url to prevent command injection
        # For this example, we assume trusted input or a more robust validation.
        result = await asyncio.to_thread(
            subprocess.run, ["git", "clone", request.repo_url, str(clone_target_dir)], capture_output=True, text=True, check=True
        )
        log_activity(f"Machine {machine_id}: Cloned Git repository '{request.repo_url}' to '{path}/{repo_name}'.")
        return {"message": f"Successfully cloned {request.repo_url} to {path}/{repo_name}", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Git clone failed: {e.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during git clone: {e}")


@app.delete("/machines/{machine_id}/files", dependencies=[Depends(authenticate_user)])
async def delete_machine_file(machine_id: str, file_path: str = Query(..., alias="path")):
    base_dir_relative = Path("workspace") / f"container-{machine_id}" / "files"
    base_dir = base_dir_relative.resolve()

    # Construct the full path to the file to be deleted
    # Ensure file_path is relative and within the base_dir for security
    clean_file_path = file_path.strip("/")  # Removed cast(str, ...)
    # Ensure clean_file_path is not empty, if it is, it means the user tried to delete the root directory
    if not clean_file_path:
        raise HTTPException(status_code=400, detail="Invalid file path: Cannot delete the root directory.")

    target_file_path = base_dir.joinpath(clean_file_path).resolve()

    # Security check: Ensure the resolved path is still within the base directory
    try:
        if not target_file_path.is_relative_to(base_dir):
            print(f"SECURITY ALERT: Attempt to delete file outside base directory: {target_file_path}")
            raise HTTPException(status_code=400, detail="Invalid file path: Not within machine's file directory.")
    except ValueError as e:
        print(f"SECURITY ALERT: ValueError during is_relative_to check for deletion: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid file path: {e}")

    if not target_file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    if target_file_path.is_dir():
        raise HTTPException(
            status_code=400, detail="Cannot delete directories using this endpoint. Use a dedicated directory deletion endpoint if needed."
        )

    try:
        os.remove(target_file_path)
        log_activity(f"Machine {machine_id}: Deleted file '{file_path}'.")
        return {"message": f"File '{file_path}' deleted successfully."}
    except OSError as e:
        print(f"ERROR: Failed to delete file {target_file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during file deletion: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


@app.delete("/machines/{machine_id}/folders", dependencies=[Depends(authenticate_user)])
async def delete_machine_folder(machine_id: str, folder_path: str = Query(..., alias="path")):
    base_dir_relative = Path("workspace") / f"container-{machine_id}" / "files"
    base_dir = base_dir_relative.resolve()

    clean_folder_path = folder_path.strip("/")
    if not clean_folder_path:
        raise HTTPException(status_code=400, detail="Invalid folder path: Cannot delete the root directory.")

    target_folder_path = base_dir.joinpath(clean_folder_path).resolve()

    try:
        if not target_folder_path.is_relative_to(base_dir):
            print(f"SECURITY ALERT: Attempt to delete folder outside base directory: {target_folder_path}")
            raise HTTPException(status_code=400, detail="Invalid folder path: Not within machine's file directory.")
    except ValueError as e:
        print(f"SECURITY ALERT: ValueError during is_relative_to check for folder deletion: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid folder path: {e}")

    if not target_folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder not found: {folder_path}")

    if not target_folder_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    try:
        shutil.rmtree(target_folder_path)
        log_activity(f"Machine {machine_id}: Deleted folder '{folder_path}'.")
        return {"message": f"Folder '{folder_path}' deleted successfully."}
    except OSError as e:
        print(f"ERROR: Failed to delete folder {target_folder_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete folder: {e}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during folder deletion: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


@app.get("/docker-images/search", dependencies=[Depends(authenticate_user)])
async def search_docker_images(query: str = Query(..., min_length=1)):
    try:
        # Use requests to search Docker Hub
        # Use requests to fetch tags for a specific image from Docker Hub
        # The 'query' parameter is now interpreted as the image name (e.g., "python")
        docker_hub_tags_url = f"https://registry.hub.docker.com/v2/repositories/library/{query.lower()}/tags?page_size=100"
        response = requests.get(docker_hub_tags_url)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

        data = response.json()
        tags = []
        for result in data.get("results", []):
            tags.append({"name": result.get("name")})  # Extract only the tag name
        return tags

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request to Docker Hub failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to search Docker images: {e}")
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to decode JSON response from Docker Hub: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse Docker Hub response: {e}")
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during Docker image search: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


@app.get("/check-unique-path-availability/{unique_id}", dependencies=[Depends(authenticate_user)])
async def check_unique_path_availability(unique_id: str):
    if not unique_id:
        raise HTTPException(status_code=400, detail="Unique ID cannot be empty.")

    try:
        response = requests.get(f"https://goto-tau.vercel.app/{unique_id}")
        if response.status_code == 209:
            return {"available": True, "status_code": response.status_code}
        else:
            return {"available": False, "status_code": response.status_code}
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request to goto-tau.vercel.app failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check unique path availability: {e}")


@app.get("/activity-logs", dependencies=[Depends(authenticate_user)])
async def get_activity_logs():
    """Returns the content of the activity log file."""
    if not ACTIVITY_LOG_FILE.is_file():
        return PlainTextResponse("No activity logs available yet.")
    try:
        with open(ACTIVITY_LOG_FILE, "r") as f:
            logs = f.read()
        return PlainTextResponse(logs)
    except Exception as e:
        print(f"ERROR: Failed to read activity log file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve activity logs: {e}")
