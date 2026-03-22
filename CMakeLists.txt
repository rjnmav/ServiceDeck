cmake_minimum_required(VERSION 3.5)

project(ServiceDeck LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt5 globally
find_package(Qt5 REQUIRED COMPONENTS Core Widgets DBus)

# Find systemd (optional)
find_package(PkgConfig REQUIRED)
pkg_check_modules(SYSTEMD IMPORTED_TARGET libsystemd)

if (SYSTEMD_FOUND)
    set(SERVICEDECK_HAS_SD_JOURNAL ON)
    message(STATUS "systemd-journal support enabled")
else()
    set(SERVICEDECK_HAS_SD_JOURNAL OFF)
    message(WARNING "systemd-journal support NOT found. Service log support will be disabled.")
endif()

# Dive into the src folder
add_subdirectory(src)