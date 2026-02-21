add_library(ViewsLib STATIC mainwindow.cpp mainwindow.h)
target_include_directories(ViewsLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ViewsLib PRIVATE PresentersLib ModelsLib Qt5::Widgets)