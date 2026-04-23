add_subdirectory(models)
add_subdirectory(services)
add_subdirectory(presenters)
add_subdirectory(views)

# Qt resource file for QSS stylesheets
qt6_add_resources(RESOURCE_FILES resources/resources.qrc)

add_executable(ServiceDeck main.cpp ${RESOURCE_FILES})

target_link_libraries(ServiceDeck PRIVATE
    ViewsLib
    PresentersLib
    ServicesLib
    ModelsLib
    Qt6::Widgets
    Qt6::DBus
)

if (SERVICEDECK_HAS_SD_JOURNAL)
    target_link_libraries(ServiceDeck PRIVATE PkgConfig::SYSTEMD)
endif()

install(TARGETS ServiceDeck
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(FILES resources/servicedeck.desktop DESTINATION share/applications)
install(FILES resources/servicedeck.svg DESTINATION share/icons/hicolor/scalable/apps)
