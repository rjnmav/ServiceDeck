add_library(ServicesLib STATIC
    systemd_dbus.cpp systemd_dbus.h
    pkexec_helper.cpp pkexec_helper.h
    unit_file_helper.cpp unit_file_helper.h
    icon_helper.cpp icon_helper.h
)
target_include_directories(ServicesLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ServicesLib PRIVATE ModelsLib Qt6::Core Qt6::DBus Qt6::Gui)