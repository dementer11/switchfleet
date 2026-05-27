from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass

from .base import CommandResult


ERROR_PATTERNS = (
    r"% ?Error",
    r"% ?Invalid",
    r"Invalid input",
    r"Error:",
    r"Ambiguous command",
    r"Incomplete command",
    r"Unrecognized command",
)

PAGER_PATTERNS = (
    r"--More--",
    r"---- More ----",
    r"More:",
    r"Press any key to continue",
)


@dataclass
class SshCredentials:
    username: str
    password: str
    enable_password: str | None = None


class ParamikoCliTransport:
    """Small prompt-driven SSH transport; device logic lives in drivers."""

    def __init__(
        self,
        host: str,
        credentials: SshCredentials,
        port: int = 22,
        timeout: float = 15.0,
        prompt_pattern: str = r"[>#\]]\s*$",
    ):
        self.host = host
        self.credentials = credentials
        self.port = port
        self.timeout = timeout
        self.prompt_pattern = re.compile(prompt_pattern)
        self.pager_patterns = tuple(re.compile(pattern, re.IGNORECASE) for pattern in PAGER_PATTERNS)
        self._client = None
        self._channel = None

    def connect(self) -> None:
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError("Paramiko is required for SSH execution") from exc

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.credentials.username,
            password=self.credentials.password,
            look_for_keys=False,
            allow_agent=False,
            timeout=self.timeout,
        )
        channel = client.invoke_shell(width=200, height=80)
        channel.settimeout(self.timeout)
        self._client = client
        self._channel = channel
        self._read_until_prompt()

    def run(self, command: str) -> CommandResult:
        if self._channel is None:
            raise RuntimeError("Transport is not connected")
        self._channel.send(command + "\n")
        output = self._read_until_prompt()
        failed = any(re.search(pattern, output, re.IGNORECASE) for pattern in ERROR_PATTERNS)
        return CommandResult(command=command, output=output, failed=failed)

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        if self._client is not None:
            self._client.close()
        self._channel = None
        self._client = None

    def _read_until_prompt(self) -> str:
        if self._channel is None:
            raise RuntimeError("Transport is not connected")

        deadline = time.monotonic() + self.timeout
        chunks: list[str] = []
        last_pager_at = -1
        while time.monotonic() < deadline:
            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(65535).decode("utf-8", errors="replace")
                    chunks.append(data)
                    buffer = "".join(chunks)
                    pager_at = _latest_match_end(self.pager_patterns, buffer)
                    if pager_at > last_pager_at:
                        last_pager_at = pager_at
                        self._channel.send(" ")
                        continue
                    if self.prompt_pattern.search(buffer):
                        return buffer
                else:
                    time.sleep(0.05)
            except socket.timeout:
                break
        return "".join(chunks)


def _latest_match_end(patterns: tuple[re.Pattern[str], ...], value: str) -> int:
    latest = -1
    for pattern in patterns:
        for match in pattern.finditer(value):
            latest = max(latest, match.end())
    return latest
