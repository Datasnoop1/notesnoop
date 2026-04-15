"""Execute commands on remote server via SSH (paramiko)."""
import os
import paramiko
import sys
import time
from dotenv import load_dotenv
load_dotenv()

HOST = os.getenv("HETZNER_IP", "")
USER = os.getenv("HETZNER_USER", "root")
PASS = os.getenv("HETZNER_PASS", "")


SSH_KEY = os.path.expanduser("~/.ssh/hetzner_datasnoop")


def run(cmd, timeout=120):
    """Execute a command on the remote server and print output."""
    if not HOST:
        raise RuntimeError("HETZNER_IP not set in environment / .env file")
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    # Try SSH key first, fall back to password
    try:
        ssh.connect(HOST, username=USER, key_filename=SSH_KEY, timeout=10)
    except Exception:
        ssh.connect(HOST, username=USER, password=PASS, timeout=10)
    print(f">>> {cmd[:80]}{'...' if len(cmd) > 80 else ''}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.strip().encode('ascii', 'replace').decode())
    if err.strip():
        print(f"STDERR: {err.strip().encode('ascii', 'replace').decode()}")
    if exit_code != 0:
        print(f"EXIT CODE: {exit_code}")
    ssh.close()
    return out, err, exit_code


if __name__ == "__main__":
    cmd = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "hostname && uname -a"
    run(cmd)
