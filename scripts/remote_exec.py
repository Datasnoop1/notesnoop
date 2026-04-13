"""Execute commands on remote server via SSH (paramiko)."""
import os
import paramiko
import sys
import time
from dotenv import load_dotenv
load_dotenv()

HOST = os.getenv("HETZNER_IP", "62.238.14.150")
USER = os.getenv("HETZNER_USER", "root")
PASS = os.getenv("HETZNER_PASS", "")


def run(cmd, timeout=120):
    """Execute a command on the remote server and print output."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
