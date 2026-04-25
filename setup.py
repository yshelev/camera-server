import subprocess
import os
from pathlib import Path

current_dir = os.getcwd()
ENV_FILE_NAME = 3
SCRIPT_PATH = "service/worker.py"
ENV_FILE_BASE = "service-environments/.env."
DOCKER_IMAGE = "my-worker:latest"

# build_cmd = ["docker", "build", "-t", DOCKER_IMAGE, "."]
# build_result = subprocess.run(build_cmd, capture_output=True, text=True)
# print(build_result)

output_containers = []

for i in range(ENV_FILE_NAME):
    env_file = ENV_FILE_BASE + str(i) 
    cmd = [
        "docker", "run", 
        "-d", 
        "--env-file", env_file,
        "-v", f"{current_dir}:/app",
        "-w", "/app",
        DOCKER_IMAGE,
        "python", SCRIPT_PATH,
        "--video", "sample.mov"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result)
    if result.returncode == 0:
        container_id = result.stdout.strip()
        output_containers.append(container_id)
        
with open("containers_id.txt", "w") as f: 
    f.write("\n".join(output_containers))