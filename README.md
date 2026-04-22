# ServiceDeck

ServiceDeck is a modern, Qt6-based desktop application designed for managing systemd services on Linux. It provides an intuitive graphical user interface for interacting with system and user services, managing unit files, and monitoring system resource usage in real-time.

⭐ **If you find ServiceDeck useful, please consider giving it a star on GitHub!** ⭐

## Features

* **Comprehensive Service Management**: View all loaded system and user services in a clear, sortable, and filterable table.
* **Core Operations**: Easily start, stop, restart, enable, disable, mask, and unmask services.
* **System & User Mode**: Seamlessly toggle between managing system-wide services and current user services via D-Bus.
* **Live Resource Monitoring**: View real-time statistics including CPU usage, memory usage, disk read/write bytes, and process/thread counts for running services.
* **Detailed Service Properties**: Inspect service states (active, sub, load) and their detailed descriptions.
* **Unit File Viewing**: Read the complete contents of systemd unit files directly from the UI without navigating through the filesystem.
* **Journal Logs**: Access the latest systemd journal logs specific to a given service to quickly diagnose issues.
* **Service Creation**: A built-in dialog allows users to create custom systemd service files from templates. Privileged operations utilize `pkexec` when creating system-level unit files.
* **Modern Interface**: Designed following Model-View-Presenter (MVP) architecture, featuring both light and dark themes and responsive components.

## Prerequisites

To build and run ServiceDeck, you need the following dependencies installed on your Linux system:

* **Qt 6** (Core, Widgets, DBus)
* **CMake** (>= 3.5)
* **A C++20 compatible compiler** (GCC or Clang)
* **systemd** (D-Bus API and optionally development headers for journal support)
* **polkit** (Provides `pkexec` for actions requiring root privileges)

### Installing Dependencies

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install build-essential cmake qtbase6-dev libqt6dbus6 libsystemd-dev policykit-1
```

**Fedora:**
```bash
sudo dnf install gcc-c++ cmake qt6-qtbase-devel systemd-devel polkit
```

**Arch Linux:**
```bash
sudo pacman -S base-devel cmake qt6-base systemd polkit systemd-libs
```

## Building and Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/rjnmav/ServiceDeck.git
   cd ServiceDeck
   ```

2. **Create a build directory:**
   ```bash
   mkdir build
   cd build
   ```

3. **Configure the build using CMake:**
   ```bash
   cmake ..
   ```

4. **Compile the application:**
   ```bash
   make -j$(nproc)
   ```

5. **Run the application:**
   ```bash
   ./src/ServiceDeck
   ```

## Architecture

ServiceDeck is built using the **Model-View-Presenter (MVP)** design pattern:
* `src/models/`: Qt Table/Filter models for systemd unit data representation.
* `src/presenters/`: Application business logic handling interactions between views and services.
* `src/services/`: Core logic handling interactions with systemd via D-Bus, executing privileged tasks (`PkexecHelper`), and reading/writing systemd unit files.
* `src/views/`: The Qt6 User Interface (Main Window, Detail Panel, Toolbars, Dialogs).

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to get started, code style guidelines, and our development workflow.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
