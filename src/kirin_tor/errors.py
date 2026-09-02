"""Domain-specific errors with stable machine-readable codes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class SourceLocation:
    path: Optional[str] = None
    entry_id: Optional[str] = None
    field: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    def render(self) -> str:
        path = self.path
        if path and self.line is not None:
            path = f"{path}:{self.line}"
            if self.column is not None:
                path += f":{self.column}"
        parts = [part for part in (path, self.entry_id, self.field) if part]
        return ": ".join(parts)


class KTError(Exception):
    code = "kirin_tor_error"

    def __init__(self, message: str, location: Optional[SourceLocation] = None):
        super().__init__(message)
        self.message = message
        self.location = location

    def __str__(self) -> str:
        prefix = self.location.render() if self.location else ""
        return f"{prefix}: {self.message}" if prefix else self.message

    def as_dict(self) -> dict:
        data = {"status": "error", "code": self.code, "message": self.message}
        if self.location:
            data["location"] = {
                key: value
                for key, value in {
                    "path": self.location.path,
                    "entry_id": self.location.entry_id,
                    "field": self.location.field,
                    "line": self.location.line,
                    "column": self.location.column,
                }.items()
                if value is not None
            }
        return data


class WorkspaceError(KTError):
    code = "workspace_error"


class PackageError(KTError):
    code = "package_error"


class PluginError(KTError):
    code = "plugin_error"


class DiscoveryError(KTError):
    code = "discovery_error"


class SchemaError(KTError):
    code = "schema_error"


class ExpressionError(KTError):
    code = "expression_error"


class ReferenceError(KTError):
    code = "reference_error"


class DependencyCycleError(KTError):
    code = "dependency_cycle"


class UnitError(KTError):
    code = "unit_error"


class ParameterError(KTError):
    code = "parameter_error"


class DomainError(KTError):
    code = "domain_error"


class MathTimeoutError(KTError):
    code = "timeout"


class UnsupportedError(KTError):
    code = "unsupported"


class ProcessExecutionError(KTError):
    code = "process_execution_error"


class ProcessFuelError(ProcessExecutionError):
    code = "process_fuel_exhausted"


class ValidationErrors(KTError):
    code = "validation_errors"

    def __init__(self, errors: Iterable[KTError]):
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} validation error(s) found")

    def __str__(self) -> str:
        lines = [self.message]
        lines.extend(f"- [{error.code}] {error}" for error in self.errors)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "status": "error",
            "code": self.code,
            "message": self.message,
            "errors": [error.as_dict() for error in self.errors],
        }

    def __reduce__(self):
        return (type(self), (self.errors,))
