add_library(ServicesLib STATIC systemd_dbus.cpp systemd_dbus.h)
target_include_directories(ServicesLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ServicesLib PRIVATE ModelsLib Qt5::DBus)