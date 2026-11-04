"""Interpret native hourly child stdout/stderr without masking typed refusals."""
from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class NativeSlotOutcome:
    kind: str
    returncode: int
    result: dict | None
    typed: dict | None
    stdout: bytes
    stderr: bytes


def interpret_native_output(returncode, stdout, stderr):
    stdout = stdout or b''
    stderr = stderr or b''
    typed = None
    if stderr.strip():
        try:
            parsed = json.loads(stderr)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            typed = parsed
    if returncode != 0:
        return NativeSlotOutcome('REFUSED', returncode, None, typed, stdout, stderr)
    if not stdout.strip():
        return NativeSlotOutcome('EMPTY_STDOUT', returncode, None, typed, stdout, stderr)
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return NativeSlotOutcome('MALFORMED_STDOUT', returncode, None, typed, stdout, stderr)
    if not isinstance(result, dict):
        return NativeSlotOutcome('MALFORMED_STDOUT', returncode, None, typed, stdout, stderr)
    return NativeSlotOutcome('PARSED', returncode, result, typed, stdout, stderr)
