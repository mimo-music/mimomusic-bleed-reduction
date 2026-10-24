// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// The app's log: every message (Qt's qDebug/qInfo/qWarning too) goes to
// work/logs/app.<host>.log with a time stamp, and stays in memory for the
// log panel.
#include <QObject>
#include <QString>
#include <QStringList>

class AppLog : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString text READ text NOTIFY changed)
    Q_PROPERTY(QString path READ path CONSTANT)
public:
    static AppLog *instance();
    void open(const QString &projectRoot);
    QString path() const { return m_path; }
    QString text() const { return m_lines.join(QLatin1Char('\n')); }
    Q_INVOKABLE void add(const QString &line);

signals:
    void changed();

private:
    QString m_path;
    QStringList m_lines;   // the last 400
};

void logInfo(const QString &s);
