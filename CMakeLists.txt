cmake_minimum_required(VERSION 3.5)

project(ServiceDeck LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt5 globally
find_package(Qt5 REQUIRED COMPONENTS Core Widgets DBus)

# Dive into the src folder
add_subdirectory(src)