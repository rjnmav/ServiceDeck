cmake_minimum_required(VERSION 4.0)

project(ServiceDeck LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt6 globally
find_package(Qt6 REQUIRED COMPONENTS Core Widgets DBus)

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

add_subdirectory(src)

set(CPACK_PACKAGE_NAME "ServiceDeck")
set(CPACK_PACKAGE_VENDOR "ServiceDeck OSS")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "Professional Qt6 Service Management Tool")
set(CPACK_PACKAGE_VERSION "1.0.0")
set(CPACK_PACKAGE_CONTACT "Rajan Panchal <rajanp1743@gmail.com>")


set(CPACK_GENERATOR "DEB")
set(CPACK_DEBIAN_PACKAGE_MAINTAINER "Rajan Panchal <rajanp1743@gmail.com>")
set(CPACK_DEBIAN_PACKAGE_HOMEPAGE "https://github.com/rjnmav/ServiceDeck")
set(CPACK_DEBIAN_PACKAGE_SECTION "utils")
set(CPACK_DEBIAN_PACKAGE_PRIORITY "optional")

set(CPACK_DEBIAN_PACKAGE_SHLIBDEPS ON)

include(CPack)
