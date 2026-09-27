#!/usr/bin/env python3
"""Keep Ollama bound to the current private IPv4 address of a macOS LAN interface.

Run under launchd (KeepAlive + RunAtLoad) and caffeinate -i. No third-party dependencies.
The installed copy lives outside the checkout, so moving the repository cannot stop service.
"""
import argparse
import ipaddress
import json
import os
import signal
import subprocess
import threading
import urllib.request


POLL_SECONDS = 5
HEALTH_FAILURE_LIMIT = 6
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


def private_ipv4(value):
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    return str(address) if any(address in network for network in PRIVATE_NETWORKS) else None


def interface_address(interface):
    try:
        result = subprocess.run(
            ["/usr/sbin/ipconfig", "getifaddr", interface],
            capture_output=True, text=True, timeout=3,
        )
        return private_ipv4(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def api_healthy(address):
    # A shell/system proxy must never redirect a local health probe off the LAN.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://{address}:11434/api/version", timeout=2) as response:
            return response.status == 200 and bool(json.load(response).get("version"))
    except (OSError, ValueError, AttributeError):
        return False


class Supervisor:
    def __init__(self, command):
        self.command = command
        self.process = None
        self.address = None
        self.failures = 0

    def stop(self):
        process = self.process
        if process is not None:
            print(f"Stopping Ollama on {self.address}:11434", flush=True)
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        self.process = None
        self.address = None
        self.failures = 0

    def tick(self, address=None, healthy=None):
        if self.process is not None:
            if healthy is not None:
                self.failures = 0 if healthy else self.failures + 1
            if self.process.poll() is not None or self.failures >= HEALTH_FAILURE_LIMIT:
                self.stop()
        if self.process is None:
            env = os.environ.copy()
            env["OLLAMA_HOST"] = "0.0.0.0:11434"
            env["OLLAMA_ORIGINS"] = "*"
            print(f"Starting Ollama on 0.0.0.0:11434 (LAN: {address})", flush=True)
            self.process = subprocess.Popen(self.command, env=env, start_new_session=True)
            self.address = "0.0.0.0"
            self.failures = 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="en1")
    parser.add_argument("--ollama", default="/opt/homebrew/opt/ollama/bin/ollama")
    args = parser.parse_args()
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    server = Supervisor([args.ollama, "serve"])
    print(f"Watching {args.interface} for a private LAN address every {POLL_SECONDS}s", flush=True)
    try:
        while not stopped.is_set():
            address = interface_address(args.interface)
            healthy = None
            if server.process and server.process.poll() is None:
                healthy = api_healthy("127.0.0.1")
            if stopped.is_set():
                break
            server.tick(address, healthy)
            stopped.wait(POLL_SECONDS)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
