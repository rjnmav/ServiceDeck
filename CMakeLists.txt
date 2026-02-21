cmake_minimum_required(VERSION 3.5)

project(ServiceDeck LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON) # Essential for Qt Signals/Slots
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt5
find_package(Qt5 REQUIRED COMPONENTS Widgets DBus)

set(PROJECT_SOURCES
    main.cpp
    mainwindow.cpp
    mainwindow.h
    servicemanager.cpp
    servicemanager.h
)

add_executable(ServiceDeck ${PROJECT_SOURCES})

target_link_libraries(ServiceDeck PRIVATE Qt5::Widgets Qt5::DBus)