"""Process-based cancellation for potentially expensive SymPy operations."""

from __future__ import annotations

import multiprocessing as mp
import math
import queue
import sys
import time
import traceback
from typing import Any, Callable, Tuple

from .errors import KTError, MathTimeoutError, ParameterError
from .limits import MAX_TIMEOUT_SECONDS


def _process_entry(result_queue, function: Callable, args: Tuple[Any, ...]) -> None:
    try:
        result_queue.put(("ok", function(*args)))
    except KTError as exc:
        result_queue.put(("kt_error", exc))
    except BaseException as exc:  # child must serialize failures, including SymPy exceptions
        result_queue.put(("error", type(exc).__name__, str(exc), traceback.format_exc()))


def run_with_timeout(function: Callable, args: tuple = (), timeout_seconds: float = 10.0):
    if (
        not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > MAX_TIMEOUT_SECONDS
    ):
        raise ParameterError(
            f"timeout must be greater than 0 and at most {MAX_TIMEOUT_SECONDS:g} seconds"
        )
    # Windows has no fork; POSIX fork keeps the standalone kernel convenient for
    # notebooks and short scripts that cannot satisfy spawn's __main__ contract.
    context = mp.get_context("spawn" if sys.platform == "win32" else "fork")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_process_entry, args=(result_queue, function, args))
    process.start()
    deadline = time.monotonic() + timeout_seconds
    message = None
    try:
        while time.monotonic() < deadline:
            try:
                message = result_queue.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                break
            except queue.Empty:
                if not process.is_alive():
                    raise RuntimeError(
                        f"mathematical worker exited with code {process.exitcode} without returning a result"
                    )
        if message is None:
            raise queue.Empty
    except queue.Empty as exc:
        process.terminate()
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join()
        raise MathTimeoutError(
            f"mathematical operation exceeded {timeout_seconds:g} seconds and its worker process was terminated"
        ) from exc
    except BaseException:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join()
        raise
    finally:
        if process.is_alive():
            process.join(timeout=0.1)
    process.join()
    if message[0] == "error":
        _, error_type, error_message, traceback_text = message
        raise RuntimeError(f"{error_type}: {error_message}\n{traceback_text}")
    if message[0] == "kt_error":
        raise message[1]
    return message[1]
