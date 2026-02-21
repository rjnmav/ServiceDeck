add_library(PresentersLib STATIC mainpresenter.cpp mainpresenter.h)
target_include_directories(PresentersLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(PresentersLib PRIVATE ServicesLib ModelsLib Qt5::Core)