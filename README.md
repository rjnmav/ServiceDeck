# ServiceDeck

ServiceDeck is a modern Linux system service management and monitoring platform. It provides a FastAPI REST backend communicating directly with `systemd` via D-Bus, paired with a PySide6 desktop GUI and a unified CLI.

---

## Key Features

- **Direct D-Bus Integration**: Asynchronous communication with `org.freedesktop.systemd1` using `dbus-fast` (no shell or `systemctl` subprocesses).
- **Polkit Aware**: Supports interactive desktop authorization prompts for privileged operations and maps access errors cleanly.
- **FastAPI Backend**: Type-safe REST API with automatic OpenAPI documentation.
- **PySide6 Desktop Client**: Responsive GUI for inspecting, starting, stopping, restarting, enabling, and disabling user and system services.
- **Unified CLI**: Single entry point to launch backend, GUI, or inspect status.

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
