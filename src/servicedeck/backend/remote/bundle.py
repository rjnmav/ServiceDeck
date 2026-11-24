"""Self-contained ``servicedeck-remote`` bundle shipped to remote hosts over SSH.

The remote host only needs ``python3`` (>= 3.10) and an SSH login; nothing is installed
there. The design follows Cockpit's "beiboot"/"beipack" bridge bootstrap:

* **Stage 2** is a single Python script holding the source of every module the agent
  imports (a subset of ``servicedeck`` plus the pure-Python ``dbus_fast`` fallback),
  an in-memory importer and the agent entrypoint. It is zlib-compressed.
* **Stage 1** is a tiny loader passed on the remote command line. It reads exactly
  ``len(payload)`` bytes of stage 2 from stdin, decompresses and executes it. After
  that, the agent speaks the normal framed protocol on the same stdin/stdout.

The payload is always built from the *local* installation, so the agent always matches
the client's protocol version. Nothing is written to the remote filesystem.
"""

from __future__ import annotations

import base64
import hashlib
import shlex
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import dbus_fast

import servicedeck

#: Minimum Python version required on the remote host. Set by ``dbus_fast``
#: (``Requires-Python >= 3.10``) and ``@dataclass(slots=True)``. Bundled modules must
#: not use newer features (``typing.Self``, ``ExceptionGroup``, ``asyncio.TaskGroup``...).
MIN_REMOTE_PYTHON = (3, 10)

#: Files/directories (relative to the ``servicedeck`` package) the agent imports.
#: Directories are included recursively. Keep this free of anything that imports
#: pydantic, FastAPI, PySide6, asyncssh or httpx — ``tests/unit/test_agent_bundle.py``
#: enforces it by running the bundle without site-packages.
AGENT_SERVICEDECK_PATHS: tuple[str, ...] = (
    "__init__.py",
    "remote",
    "remote_agent",
    "backend/__init__.py",
    "backend/exceptions.py",
    "backend/models",
    "backend/core/__init__.py",
    "backend/core/service_manager.py",
    "backend/infrastructure/__init__.py",
    "backend/infrastructure/dbus",
)

#: Sub-packages of ``dbus_fast`` that the agent never imports.
_DBUS_FAST_EXCLUDED_DIRS = frozenset({"glib", "__pycache__"})

_BUNDLE_FILENAME_PREFIX = "<servicedeck-agent>"

_STAGE2_RUNTIME = '''
import importlib.abc
import importlib.util
import linecache
import sys

_PREFIX = {prefix!r}


class _BundleImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves modules from the in-memory SOURCES table, ahead of anything installed."""

    def _lookup(self, fullname):
        base = fullname.replace(".", "/")
        if base + "/__init__.py" in SOURCES:
            return base + "/__init__.py", True
        if base + ".py" in SOURCES:
            return base + ".py", False
        return None

    def find_spec(self, fullname, path=None, target=None):
        found = self._lookup(fullname)
        if found is None:
            return None
        relpath, is_pkg = found
        return importlib.util.spec_from_loader(
            fullname, self, origin=_PREFIX + "/" + relpath, is_package=is_pkg
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        relpath, _ = self._lookup(module.__name__)
        filename = _PREFIX + "/" + relpath
        source = SOURCES[relpath]
        # Keep remote tracebacks readable (mtime None => never invalidated).
        linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
        exec(compile(source, filename, "exec", dont_inherit=True), module.__dict__)


sys.meta_path.insert(0, _BundleImporter())
sys.argv = ["servicedeck-remote", *ARGV]
'''

_STAGE2_ENTRYPOINT = """
from servicedeck.remote_agent.main import main

sys.exit(main(ARGV))
"""

# Stage 1 must run on *any* python3 far enough to report a clear version error,
# so it avoids f-strings and other modern syntax.
_STAGE1_SOURCE = """\
import os, sys
if sys.version_info < {min_version!r}:
    sys.exit("servicedeck: remote python3 >= {min_str} required, found %d.%d" % sys.version_info[:2])
import zlib
n = int(sys.argv[1])
buf = bytearray()
while len(buf) < n:
    chunk = os.read(0, n - len(buf))
    if not chunk:
        sys.exit("servicedeck: bootstrap payload truncated (%d/%d bytes)" % (len(buf), n))
    buf += chunk
exec(compile(zlib.decompress(bytes(buf)), {prefix!r}, "exec", dont_inherit=True), {{"__name__": "__main__"}})
"""

#: Marker printed by stage 1 when the remote interpreter is too old.
PYTHON_TOO_OLD_MARKER = "servicedeck: remote python3 >="


@dataclass(frozen=True, slots=True)
class AgentPayload:
    """Compressed stage-2 bundle plus metadata."""

    data: bytes
    sha256: str
    module_count: int
    raw_size: int


def _iter_py_files(root: Path, excluded_dirs: frozenset[str] = frozenset()) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        rel_parts = path.relative_to(root).parts
        if any(part in excluded_dirs or part == "__pycache__" for part in rel_parts[:-1]):
            continue
        files.append(path)
    return files


def collect_agent_sources() -> dict[str, str]:
    """Collect ``{"pkg/mod.py": source}`` for every module the remote agent needs."""
    sources: dict[str, str] = {}

    servicedeck_root = Path(servicedeck.__file__).resolve().parent
    for entry in AGENT_SERVICEDECK_PATHS:
        path = servicedeck_root / entry
        if path.is_dir():
            files = _iter_py_files(path)
        elif path.is_file():
            files = [path]
        else:
            raise FileNotFoundError(f"Agent bundle entry missing from installation: {path}")
        for file in files:
            rel = "servicedeck/" + file.relative_to(servicedeck_root).as_posix()
            sources[rel] = file.read_text(encoding="utf-8")

    dbus_fast_root = Path(dbus_fast.__file__).resolve().parent
    for file in _iter_py_files(dbus_fast_root, _DBUS_FAST_EXCLUDED_DIRS):
        rel = "dbus_fast/" + file.relative_to(dbus_fast_root).as_posix()
        sources[rel] = file.read_text(encoding="utf-8")

    return sources


def build_stage2(
    argv: tuple[str, ...] = (),
    *,
    entrypoint: str = _STAGE2_ENTRYPOINT,
    sources: dict[str, str] | None = None,
) -> str:
    """Render the stage-2 script: sources table, importer and entrypoint."""
    table = sources if sources is not None else collect_agent_sources()
    return "\n".join(
        (
            f"SOURCES = {table!r}",
            f"ARGV = {list(argv)!r}",
            _STAGE2_RUNTIME.format(prefix=_BUNDLE_FILENAME_PREFIX),
            entrypoint,
        )
    )


def build_payload(
    argv: tuple[str, ...] = (),
    *,
    entrypoint: str = _STAGE2_ENTRYPOINT,
) -> AgentPayload:
    """Build and compress a stage-2 payload (uncached; see :func:`get_agent_payload`)."""
    sources = collect_agent_sources()
    stage2 = build_stage2(argv, entrypoint=entrypoint, sources=sources).encode("utf-8")
    data = zlib.compress(stage2, level=9)
    return AgentPayload(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        module_count=len(sources),
        raw_size=len(stage2),
    )


@lru_cache(maxsize=4)
def get_agent_payload(argv: tuple[str, ...] = ()) -> AgentPayload:
    """Return the cached agent payload for the given agent CLI arguments."""
    return build_payload(argv)


def stage1_source() -> str:
    """Return the stage-1 loader source."""
    return _STAGE1_SOURCE.format(
        min_version=MIN_REMOTE_PYTHON,
        min_str=".".join(map(str, MIN_REMOTE_PYTHON)),
        prefix=_BUNDLE_FILENAME_PREFIX,
    )


def stage1_command(payload_len: int, python: str = "python3") -> str:
    """Return the remote shell command that boots the agent from stdin.

    The loader is base64-encoded so the command is a single line made only of
    shell-safe characters, which works under sh, bash, zsh, fish and csh alike.
    ``exec`` replaces the login shell so signals and PR_SET_PDEATHSIG reach Python.
    """
    encoded = base64.b64encode(stage1_source().encode("ascii")).decode("ascii")
    loader = f'import base64;exec(base64.b64decode("{encoded}"))'
    return shlex.join(["exec", python, "-c", loader, str(payload_len)])


__all__ = [
    "AGENT_SERVICEDECK_PATHS",
    "MIN_REMOTE_PYTHON",
    "PYTHON_TOO_OLD_MARKER",
    "AgentPayload",
    "build_payload",
    "build_stage2",
    "collect_agent_sources",
    "get_agent_payload",
    "stage1_command",
    "stage1_source",
]
