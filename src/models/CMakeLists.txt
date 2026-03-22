add_library(ModelsLib STATIC
    unit_model.cpp unit_model.h
    service_table_model.cpp service_table_model.h
    service_filter_model.cpp service_filter_model.h
    app_preferences.cpp app_preferences.h
)
target_include_directories(ModelsLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ModelsLib PRIVATE Qt5::Core Qt5::DBus Qt5::Gui)