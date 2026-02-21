add_library(ModelsLib STATIC unit_model.cpp unit_model.h)
target_include_directories(ModelsLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ModelsLib PRIVATE Qt5::DBus)