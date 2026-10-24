// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

// Bleed Reduction: projects with import, roles and render (Product.qml, Studio).
//   bleed-reduction --project <bleed_reduction folder>
//   bleed-reduction --project ... --gui-test --test-project <project>
//                         opens the window, runs the self-test on a copy of that project, quits
//                         (exit code 0 = fine); --screenshots <dir> also saves the views as PNG
// Built with BLEED_WORKBENCH (the development tree), the same program is also the Bleed
// Workbench (listen, compare, rate, mark), and the product only with --product or as
// bleed-reduction.
#include "AppLog.h"
#include "Markers.h"
#include "Player.h"
#ifdef BLEED_WORKBENCH
#include "Project.h"
#endif
#include "Studio.h"
#include "TestDriver.h"

#include <QCommandLineParser>
#include <QDir>
#include <QFileInfo>
#include <QGuiApplication>
#include <QPalette>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QTimer>

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE"))
        QQuickStyle::setStyle(QStringLiteral("Fusion"));
    {
        // dark, like the MimoMusic plugins
        QPalette p;
        const QColor text(230, 232, 236), dim(140, 144, 152);
        p.setColor(QPalette::Window, QColor(24, 25, 29));
        p.setColor(QPalette::WindowText, text);
        p.setColor(QPalette::Base, QColor(18, 19, 23));
        p.setColor(QPalette::AlternateBase, QColor(32, 34, 40));
        p.setColor(QPalette::Text, text);
        p.setColor(QPalette::PlaceholderText, dim);
        p.setColor(QPalette::Button, QColor(52, 56, 64));
        p.setColor(QPalette::ButtonText, text);
        p.setColor(QPalette::BrightText, Qt::white);
        p.setColor(QPalette::Highlight, QColor(70, 130, 160));
        p.setColor(QPalette::HighlightedText, Qt::white);
        p.setColor(QPalette::Light, QColor(90, 94, 100));
        p.setColor(QPalette::Midlight, QColor(64, 68, 76));
        p.setColor(QPalette::Mid, QColor(78, 84, 96));
        p.setColor(QPalette::Dark, QColor(14, 15, 18));
        p.setColor(QPalette::Shadow, Qt::black);
        p.setColor(QPalette::ToolTipBase, QColor(44, 47, 54));
        p.setColor(QPalette::ToolTipText, text);
        p.setColor(QPalette::Link, QColor(120, 200, 255));
        p.setColor(QPalette::Disabled, QPalette::Text, QColor(100, 104, 112));
        p.setColor(QPalette::Disabled, QPalette::ButtonText, QColor(100, 104, 112));
        p.setColor(QPalette::Disabled, QPalette::WindowText, QColor(100, 104, 112));
        QGuiApplication::setPalette(p);
    }
#ifdef BLEED_WORKBENCH
    const bool product = QFileInfo(QString::fromLocal8Bit(argv[0])).fileName() == QLatin1String("bleed-reduction")
                         || QCoreApplication::arguments().contains(QStringLiteral("--product"));
#else
    const bool product = true;
#endif
    app.setApplicationName(product ? QStringLiteral("Bleed Reduction") : QStringLiteral("Bleed Workbench"));
    app.setOrganizationName(QStringLiteral("MimoMusic"));

    QCommandLineParser cl;
    cl.addHelpOption();
    QCommandLineOption proj(QStringLiteral("project"), QStringLiteral("the bleed_reduction folder"), QStringLiteral("dir"),
                            QDir::currentPath());
    QCommandLineOption guiTest(QStringLiteral("gui-test"), QStringLiteral("load, check the views, quit"));
    QCommandLineOption shots(QStringLiteral("screenshots"), QStringLiteral("with --gui-test: save a PNG of every tab here"),
                             QStringLiteral("dir"));
    QCommandLineOption audio(QStringLiteral("audio-info"), QStringLiteral("show the audio output and the rates it takes"));
    QCommandLineOption productOpt(QStringLiteral("product"), QStringLiteral("the product app (projects, import, render)"));
    QCommandLineOption testProject(QStringLiteral("test-project"), QStringLiteral("with --product --gui-test: the project to test with"),
                                   QStringLiteral("dir"));
    cl.addOptions({proj, guiTest, shots, audio, productOpt, testProject});
    cl.process(app);
    if (cl.isSet(audio)) {
        printf("%s\n", qPrintable(Player::audioInfo()));
        return 0;
    }

    const QString root = QDir(cl.value(proj)).absolutePath();
    if (product) {
        if (!QFileInfo::exists(root + QStringLiteral("/tools/render.py"))) {
            fprintf(stderr, "%s has no tools/render.py: give the bleed_reduction folder with --project\n", qPrintable(root));
            return 2;
        }
        AppLog::instance()->open(root);
        Studio studio(root);
        Player player;
        Markers markers(root);          // the waveform editor asks it for tag colours
        QQmlApplicationEngine engine;
        auto *ctx = engine.rootContext();
        ctx->setContextProperty(QStringLiteral("studio"), &studio);
        ctx->setContextProperty(QStringLiteral("player"), &player);
        ctx->setContextProperty(QStringLiteral("markers"), &markers);
        ctx->setContextProperty(QStringLiteral("appLog"), AppLog::instance());
        ctx->setContextProperty(QStringLiteral("guiTest"), cl.isSet(guiTest));
        ctx->setContextProperty(QStringLiteral("screenshotDir"), cl.value(shots));
        ctx->setContextProperty(QStringLiteral("productTestProject"), cl.value(testProject));
        TestDriver productDriver;
        ctx->setContextProperty(QStringLiteral("driver"), &productDriver);
        int warnings = 0;
        QObject::connect(&engine, &QQmlApplicationEngine::warnings, [&warnings](const QList<QQmlError> &w) {
            for (const QQmlError &e : w)
                qWarning("QML: %s", qPrintable(e.toString()));
            warnings += int(w.size());
        });
        engine.loadFromModule("Bleed", "Product");
        if (engine.rootObjects().isEmpty())
            return 1;
        if (cl.isSet(guiTest))
            QTimer::singleShot(60000, &app, [] { qWarning("product-test: timeout"); QCoreApplication::exit(3); });
        const int rc = app.exec();
        return cl.isSet(guiTest) && rc == 0 && warnings ? 4 : rc;
    }
#ifdef BLEED_WORKBENCH
    if (!QDir(root + QStringLiteral("/output/songs")).exists()) {
        fprintf(stderr, "%s has no output/songs: give the bleed_reduction folder with --project\n", qPrintable(root));
        return 2;
    }
    AppLog::instance()->open(root);
    Project project(root);
    Player player;
    Markers markers(root);

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("project"), &project);
    engine.rootContext()->setContextProperty(QStringLiteral("player"), &player);
    engine.rootContext()->setContextProperty(QStringLiteral("markers"), &markers);
    engine.rootContext()->setContextProperty(QStringLiteral("appLog"), AppLog::instance());
    engine.rootContext()->setContextProperty(QStringLiteral("guiTest"), cl.isSet(guiTest));
    TestDriver driver;
    engine.rootContext()->setContextProperty(QStringLiteral("driver"), &driver);
    engine.rootContext()->setContextProperty(QStringLiteral("screenshotDir"), cl.value(shots));
    int warnings = 0;
    QObject::connect(&engine, &QQmlApplicationEngine::warnings, [&warnings](const QList<QQmlError> &w) {
        for (const QQmlError &e : w)
            qWarning("QML: %s", qPrintable(e.toString()));
        warnings += int(w.size());
    });
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);
    engine.loadFromModule("Bleed", "Main");
    if (engine.rootObjects().isEmpty())
        return 1;
    if (cl.isSet(guiTest)) {
        // Main.qml runs its own steps when guiTest is set and reports "gui-test: ok"
        QTimer::singleShot(60000, &app, [] { qWarning("gui-test: timeout"); QCoreApplication::exit(3); });
        const int rc = app.exec();
        return rc == 0 && warnings ? 4 : rc;
    }
    return app.exec();
#endif
}
