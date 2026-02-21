add_subdirectory(models)
add_subdirectory(services)
add_subdirectory(presenters)
add_subdirectory(views)

add_executable(ServiceDeck main.cpp)

target_link_libraries(ServiceDeck PRIVATE ViewsLib PresentersLib ServicesLib ModelsLib Qt5::Widgets Qt5::DBus)