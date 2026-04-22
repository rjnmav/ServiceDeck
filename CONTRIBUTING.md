# Contributing to ServiceDeck

First off, thank you for considering contributing to ServiceDeck!

## Where do I go from here?

If you've noticed a bug or have a feature request, make one! It's generally best if you get confirmation of your bug or approval for your feature request before starting to code.

## Getting Started

1. Fork the repository on GitHub.
2. Clone your fork locally.
3. Follow the build instructions in the `README.md` to ensure you can compile the application.

## Development Workflow

1. Create a new branch for your feature or bugfix:
   ```bash
   git checkout -b feature/my-awesome-feature
   ```
   or
   ```bash
   git checkout -b fix/issue-number
   ```
2. Make your changes in your local branch.
3. Ensure the project still builds successfully:
   ```bash
   cd build
   cmake ..
   make -j$(nproc)
   ```
4. Push your branch to your fork on GitHub:
   ```bash
   git push origin your-branch-name
   ```
5. Open a Pull Request against the `main` branch of the original repository.

## Coding Conventions

ServiceDeck is built using modern C++ (C++20) and Qt6. Please adhere to the following guidelines:

* **Architecture**: The project strictly follows the **Model-View-Presenter (MVP)** pattern.
  * Keep your views (UI code) as "dumb" or passive as possible.
  * Put business logic, state handling, and view-coordination into the `presenters/`.
  * Put backend logic, file I/O, and D-Bus interactions into `services/`.
* **Naming Conventions**:
  * Classes are `PascalCase` (e.g., `SystemdDBus`).
  * Methods and local variables are `camelCase` (e.g., `fetchServiceResourceUsage`).
  * Class member variables are prefixed with `m_` (e.g., `m_useSystemBus`).
* **Memory Management**: Use Qt's parent-child object tree for memory management where applicable. When creating `QObject` subclasses, always pass `this` as the parent when appropriate.
* **Error Handling**: When interacting with external systems (like D-Bus or pkexec), return appropriate error structures (like `OperationResult` or `PkexecResult`) rather than failing silently or throwing raw exceptions.
* **UI Styling**: All styling should be done via Qt Style Sheets (`.qss` files in `src/resources/`), rather than hardcoding colors or styles directly in the C++ code.

## D-Bus Interactions

Any new interaction with systemd should be added to `src/services/systemd_dbus.h/cpp`. Please avoid scattering D-Bus calls throughout presenters or views.

## Reporting Bugs

When reporting bugs, please include:
1. Your Operating System and version.
2. The version of Qt6 and systemd you are using.
3. Detailed steps to reproduce the bug.
4. Any relevant console output or crash logs.

Thank you for contributing!
