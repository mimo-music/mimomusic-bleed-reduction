# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

# Bleed Reduction: the app for projects (import, roles, render; Product.qml, Studio). Built by
# ../install.sh into ../../builds/bleed_reduction/app (outside the project: each computer its own).
# With qml/Main.qml present (the development tree) it is the Bleed Workbench as well: one program,
# bleed-workbench, that is the product with --product; without it, only bleed-reduction is built.
cmake_minimum_required(VERSION 3.21)
project(bleed_reduction VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2 Multimedia Test)
find_package(PkgConfig REQUIRED)
pkg_check_modules(SNDFILE REQUIRED IMPORTED_TARGET sndfile)

qt_standard_project_setup(REQUIRES 6.5)   # also sets the QML resource-path policies

set(CORE_SOURCES
    src/AudioFile.h src/AudioFile.cpp
    src/Player.h src/Player.cpp
    src/AudioCache.h src/AudioCache.cpp
    src/WaveView.h src/WaveView.cpp
    src/Markers.h src/Markers.cpp
    src/AppLog.h src/AppLog.cpp
    src/TestDriver.h src/TestDriver.cpp
    src/Studio.h src/Studio.cpp
)
set(QML_FILES
    qml/Product.qml
    qml/Theme.qml
    qml/Timeline.qml
    qml/ValueBox.qml
    qml/Btn.qml
)

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/qml/Main.qml)
    set(APP bleed-workbench)
    list(APPEND CORE_SOURCES src/Project.h src/Project.cpp)
    list(APPEND QML_FILES
        qml/Main.qml
        qml/ListenView.qml
        qml/MarkersView.qml
        qml/DebugView.qml
        qml/JobsView.qml
        qml/VersionCard.qml
        qml/Stars.qml
        qml/PassageTable.qml
    )
else()
    set(APP bleed-reduction)
endif()

qt_add_executable(${APP} src/main.cpp)
set_source_files_properties(qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
qt_add_qml_module(${APP}
    URI Bleed
    VERSION 1.0
    QML_FILES ${QML_FILES}
    SOURCES ${CORE_SOURCES}
)
target_include_directories(${APP} PRIVATE src)
target_link_libraries(${APP} PRIVATE
    Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2 Qt6::Multimedia Qt6::Test PkgConfig::SNDFILE)
if(APP STREQUAL bleed-workbench)
    target_compile_definitions(${APP} PRIVATE BLEED_WORKBENCH)
endif()

# core self-test of the Workbench (no window, no sound card needed): ctest or ./bleed-workbench-test
if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/tests/core_test.cpp AND APP STREQUAL bleed-workbench)
    qt_add_executable(bleed-workbench-test tests/core_test.cpp ${CORE_SOURCES})
    target_include_directories(bleed-workbench-test PRIVATE src)
    target_link_libraries(bleed-workbench-test PRIVATE
        Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::Multimedia Qt6::Test PkgConfig::SNDFILE)
    enable_testing()
    add_test(NAME core COMMAND bleed-workbench-test ${CMAKE_CURRENT_SOURCE_DIR}/..)
endif()
