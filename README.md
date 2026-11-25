# ServiceDeck

ServiceDeck is a modern Linux system service management and monitoring platform. It provides a FastAPI REST backend communicating directly with `systemd` via D-Bus, paired with a PySide6 desktop GUI and a unified CLI.

---

## Key Features

- **Direct D-Bus Integration**: Asynchronous communication with `org.freedesktop.systemd1` using `dbus-fast` (no shell or `systemctl` subprocesses).
- **Polkit Aware**: Supports interactive desktop authorization prompts for privileged operations and maps access errors cleanly.
- **FastAPI Backend**: Type-safe REST API with automatic OpenAPI documentation.
- **PySide6 Desktop Client**: Responsive GUI for inspecting, starting, stopping, restarting, enabling, and disabling user and system services.
- **Live Updates**: The service list follows systemd's D-Bus change signals (locally and on remote hosts), updating rows in place and highlighting state changes such as a crash.
- **Followed Logs**: `journalctl -f` style log view with pause, auto-scroll and filtering.
- **Unified CLI**: Single entry point to launch the backend or GUI, and to list, inspect, control and tail services from scripts and terminals.

---

## System Requirements

- **OS**: Linux with `systemd` and `D-Bus`
- **Python**: 3.12+

---

## Installation

Clone the repository and install dependencies in your virtual environment:

```bash
git clone https://github.com/your-org/servicedeck-2.0.git
cd servicedeck-2.0

# Install package with development dependencies
pip install -e ".[dev]"
```

---

## Usage

### 1. Unified CLI

Launch any component using the `servicedeck` command:

```bash
# Start backend server
servicedeck backend

# Start desktop GUI client
servicedeck gui
```

With the backend running, manage services straight from the terminal. `--host <device>`
targets a configured remote machine, `--scope system` (or `--system`) the system services,
and `--json` gives machine-readable output:

```bash
servicedeck list                       # all user services
servicedeck list --system --failed     # failed system services
servicedeck list 'pipewire*' --json    # glob filter, JSON output
servicedeck status nginx --host srv1 --system
servicedeck restart nginx php-fpm --host srv1 --system
servicedeck enable --system nginx
servicedeck logs nginx -n 50 --system  # last 50 journal lines
servicedeck logs nginx -f --system     # follow, like journalctl -f (Ctrl-C to stop)
```

`status` exits with 0 when the service is active, 3 when it is not, and 4 when it does not
exist (as `systemctl status` does). If a remote system-service command needs administrator
access, the CLI tries passwordless sudo and otherwise asks for the sudo password once.

### 2. Standalone Entry Points

You can also run the components independently:

**Backend Server:**
```bash
servicedeck-backend --host 127.0.0.1 --port 8000
```
Interactive API documentation will be available at:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

**Desktop GUI:**
```bash
servicedeck-gui --url http://127.0.0.1:8000
```

**Remote Management:**
```bash
# Add a remote machine configuration
servicedeck remote add srv1 192.168.1.50 --username alice

# List configured remote machines
servicedeck remote list

# See complete remote guide:
# docs/remote_connection_guide.md
```

---

## Development & Testing

Run the test suite:
```bash
pytest -v
```

Check code formatting and linting:
```bash
ruff check .
ruff format --check .
```

---
