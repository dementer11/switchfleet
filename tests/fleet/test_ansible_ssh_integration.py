"""Exercise real Ansible processes and real SSH against a local test switch.

No inventory or addresses from the operator are used by these tests.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
from collections.abc import Iterator
from typing import Any

import paramiko
import pytest

from app.fleet.ansible_engine import AnsibleEngine
from app.fleet.profiles import build_device_plan

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or importlib.util.find_spec("ansible_runner") is None,
    reason="Real Ansible integration requires a POSIX controller with ansible-runner",
)


class _SSHServer(paramiko.ServerInterface):
    def __init__(self) -> None:
        self.shell = threading.Event()

    def check_auth_password(self, username: str, password: str) -> int:
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("test-operator", "TestOnly-SSH-Secret") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel: Any, term: Any, width: Any, height: Any, pixelwidth: Any, pixelheight: Any, modes: Any) -> bool:
        return True

    def check_channel_shell_request(self, channel: Any) -> bool:
        self.shell.set()
        return True


class LocalSwitch:
    def __init__(self) -> None:
        self.key = paramiko.RSAKey.generate(2048)
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(10)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.closed = threading.Event()
        self.commands: list[str] = []
        self.vlans: set[int] = {10}
        self.transports: list[paramiko.Transport] = []
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def _listen(self) -> None:
        while not self.closed.is_set():
            try:
                client, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._session, args=(client,), daemon=True).start()

    def _session(self, client: socket.socket) -> None:
        transport = paramiko.Transport(client)
        self.transports.append(transport)
        try:
            transport.add_server_key(self.key)
            server = _SSHServer()
            transport.start_server(server=server)
            channel = transport.accept(10)
            if channel is None or not server.shell.wait(10):
                return
            channel.sendall(b"Test switch\r\nsf-test# ")
            pending = ""
            while transport.is_active() and not self.closed.is_set():
                data = channel.recv(4096)
                if not data:
                    break
                pending += data.decode("utf-8", errors="replace").replace("\r", "")
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    command = line.strip()
                    self.commands.append(command)
                    output = self._answer(command)
                    channel.sendall((command + "\r\n" + output + "\r\nsf-test# ").encode())
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            transport.close()

    def _answer(self, command: str) -> str:
        if command in {"show running-config", "display current-configuration"}:
            return "hostname sf-test\r\n" + "\r\n".join(f"vlan {vlan}" for vlan in sorted(self.vlans)) + "\r\nsnmp-server community FixtureCommunitySecret ro\r\nend"
        if command in {"show version", "display version"}:
            return "SwitchFleet local SSH fixture, version 1.0"
        if command.startswith("vlan ") and command.split()[-1].isdigit():
            self.vlans.add(int(command.split()[-1]))
            return ""
        if command.startswith(("show vlan", "display vlan")):
            return "\r\n".join(f"VLAN {vlan} active" for vlan in sorted(self.vlans))
        if command == "fail-command":
            return "% Invalid input detected"
        if command in {"write memory", "save", "save force"}:
            return "Configuration saved"
        return ""

    def close(self) -> None:
        self.closed.set()
        self.listener.close()
        for transport in self.transports:
            transport.close()
        self.thread.join(timeout=2)


@pytest.fixture()
def local_switch() -> Iterator[LocalSwitch]:
    switch = LocalSwitch()
    try:
        yield switch
    finally:
        switch.close()


def _device(local_switch: LocalSwitch, identifier: str = "local-test") -> dict[str, Any]:
    return {"id": identifier, "label": "Local SSH test", "ip_address": "127.0.0.1", "port": local_switch.port, "family": "qtech"}


def _credential() -> dict[str, str]:
    return {"username": "test-operator", "password": "TestOnly-SSH-Secret"}


def test_real_ansible_backup_and_partial_host_failure(local_switch: LocalSwitch) -> None:
    engine = AnsibleEngine()
    assert engine.available()["available"] is True
    good = build_device_plan(_device(local_switch, "good"), "backup", {})
    bad = build_device_plan(_device(local_switch, "bad"), "backup", {})
    events: list[dict[str, Any]] = []
    results = engine.run(
        [good, bad], {"good": _credential(), "bad": {"username": "test-operator", "password": "IncorrectTestPassword"}},
        on_event=events.append, forks=2,
    )
    by_id = {row["device_id"]: row for row in results}
    assert by_id["good"]["status"] == "succeeded", results
    assert by_id["bad"]["status"] == "failed", results
    assert "hostname sf-test" in by_id["good"]["backup_text"]
    assert "FixtureCommunitySecret" not in json.dumps(results)
    assert "TestOnly-SSH-Secret" not in json.dumps(events)
    assert "IncorrectTestPassword" not in json.dumps(results)


def test_real_ansible_configure_has_prechange_backup(local_switch: LocalSwitch) -> None:
    device = _device(local_switch)
    plan = build_device_plan(device, "configure", {"commands": ["configure terminal", "vlan 123", "end", "write memory"]})
    assert plan["status"] == "ready", plan
    result = AnsibleEngine().run([plan], {device["id"]: _credential()})[0]
    assert result["status"] == "succeeded", result
    assert result["changed"] is True
    assert "vlan 123" not in result["backup_text"]
    assert 123 in local_switch.vlans
    assert local_switch.commands.index("show running-config") < local_switch.commands.index("vlan 123")


def test_real_ansible_cisco_netmiko_template(local_switch: LocalSwitch) -> None:
    device = {**_device(local_switch, "cisco-test"), "family": "cisco_ios"}
    plan = build_device_plan(device, "vlan_create", {"vlan_id": 234, "name": "TEST"})
    assert plan["status"] == "ready", plan
    result = AnsibleEngine().run([plan], {device["id"]: _credential()})[0]
    assert result["status"] == "succeeded", result
    assert "vlan 234" not in result["backup_text"]
    assert 234 in local_switch.vlans
    assert local_switch.commands.index("show running-config") < local_switch.commands.index("vlan 234")
    assert "show vlan id 234" in local_switch.commands
