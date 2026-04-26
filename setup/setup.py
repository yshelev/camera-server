import subprocess
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
current_dir = os.getcwd()

DOCKER_NETWORK = os.getenv("NETWORK")
ENV_FILES_NUM = 3
SCRIPT_PATH = "service/worker.py"
ENV_FILE_BASE = "service-environments/.env."
DOCKER_IMAGE = "my-worker:latest"

subprocess.run(
    ["docker", "rm", "-f"] + [f"worker_{i}" for i in range(ENV_FILES_NUM)],
    capture_output=True, 
)
output_containers = []

for i in range(ENV_FILES_NUM):
    env_file = ENV_FILE_BASE + str(i) 
    container_name = f"worker_{i}"
    
    cmd = [
        "docker", "run", 
        "-d", 
        "--name", container_name, 
        "--network", DOCKER_NETWORK, 
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