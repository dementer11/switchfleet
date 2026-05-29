from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass

from ..models import CommandStep, PromptResponse
from .base import CommandResult
from .errors import output_has_cli_error


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
        read_timeout: float | None = None,
        prompt_pattern: str = r"[>#\]]\s*$",
    ):
        self.host = host
        self.credentials = credentials
        self.port = port
        self.timeout = timeout
        self.read_timeout = read_timeout or timeout
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
        self._read_until_prompt(self.timeout)
        if self.credentials.enable_password:
            self._enter_enable_mode()

    def run(self, command: str) -> CommandResult:
        return self.run_step(CommandStep(command))

    def run_step(self, step: CommandStep) -> CommandResult:
        if self._channel is None:
            raise RuntimeError("Transport is not connected")
        self._channel.send(step.command + "\n")
        output, completed = self._read_until_prompt(self.read_timeout, step)
        error = None if completed else f"Timed out waiting for prompt after {self.read_timeout:.1f}s"
        return CommandResult(
            command=step.command,
            output=output,
            failed=(not completed) or output_has_cli_error(output, step.error_patterns),
            phase=step.phase.value,
            redacted_command="<redacted>" if step.secret else step.command,
            error=error,
        )

    def run_steps(self, steps: tuple[CommandStep, ...], stop_on_error: bool = True) -> list[CommandResult]:
        results: list[CommandResult] = []
        for step in steps:
            result = self.run_step(step)
            results.append(result)
            if result.failed and stop_on_error:
                break
        return results

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        if self._client is not None:
            self._client.close()
        self._channel = None
        self._client = None

    def _enter_enable_mode(self) -> None:
        step = CommandStep(
            "enable",
            responses=(PromptResponse(r"password:", self.credentials.enable_password or "", hidden=True),),
            expected_prompt=r"#\s*$",
        )
        result = self.run_step(step)
        if result.failed:
            raise RuntimeError(f"Failed to enter enable mode on {self.host}: {result.error or 'CLI rejected enable'}")

    def _read_until_prompt(self, timeout: float, step: CommandStep | None = None) -> tuple[str, bool]:
        if self._channel is None:
            raise RuntimeError("Transport is not connected")

        deadline = time.monotonic() + timeout
        chunks: list[str] = []
        last_pager_at = -1
        response_patterns = tuple(
            re.compile(response.pattern, re.IGNORECASE)
            for response in (step.responses if step else ())
        )
        responded: set[int] = set()
        prompt_pattern = re.compile(step.expected_prompt) if step and step.expected_prompt else self.prompt_pattern
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
                    sent_response = False
                    for index, pattern in enumerate(response_patterns):
                        if index not in responded and pattern.search(buffer):
                            responded.add(index)
                            self._channel.send(step.responses[index].response + "\n")
                            sent_response = True
                            break
                    if sent_response:
                        continue
                    if prompt_pattern.search(buffer):
                        return buffer, True
                else:
                    time.sleep(0.05)
            except socket.timeout:
                break
        return "".join(chunks), False


def _latest_match_end(patterns: tuple[re.Pattern[str], ...], value: str) -> int:
    latest = -1
    for pattern in patterns:
        for match in pattern.finditer(value):
            latest = max(latest, match.end())
    return latest
