// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "AppLog.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QSysInfo>
#include <QMetaObject>
#include <QTextStream>
#include <QThread>
#include <QCoreApplication>

AppLog *AppLog::instance()
{
    static AppLog log;
    return &log;
}

static void handler(QtMsgType type, const QMessageLogContext &, const QString &msg)
{
    static const char *names[] = {"debug", "warning", "critical", "fatal", "info"};
    const QString line = QStringLiteral("%1 %2").arg(QLatin1String(names[type]), msg);
    AppLog *l = AppLog::instance();
    if (QThread::currentThread() == l->thread())
        l->add(line);
    else
        QMetaObject::invokeMethod(l, [l, line] { l->add(line); }, Qt::QueuedConnection);
    fprintf(stderr, "%s\n", qPrintable(line));
}

void AppLog::open(const QString &projectRoot)
{
    QDir().mkpath(projectRoot + QStringLiteral("/work/logs"));
    m_path = projectRoot + QStringLiteral("/work/logs/app.%1.log").arg(QSysInfo::machineHostName());
    qInstallMessageHandler(handler);
    add(QStringLiteral("---- start, Qt %1, project %2").arg(QLatin1String(qVersion()), projectRoot));
}

void AppLog::add(const QString &line)
{
    const QString l = QDateTime::currentDateTime().toString(QStringLiteral("HH:mm:ss ")) + line;
    m_lines << l;
    if (m_lines.size() > 400)
        m_lines.removeFirst();
    if (!m_path.isEmpty()) {
        QFile f(m_path);
        if (f.open(QIODevice::Append | QIODevice::Text))
            QTextStream(&f) << QDate::currentDate().toString(Qt::ISODate) << ' ' << l << '\n';
    }
    emit changed();
}

void logInfo(const QString &s) { AppLog::instance()->add(s); }
