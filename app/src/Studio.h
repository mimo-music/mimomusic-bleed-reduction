// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// A Bleed Reduction project: a folder with project.json
// (tools/project.py). Import (a folder of stems, or an Ardour session) and analysis run
// tools/project.py; the render runs tools/render.py detached (it keeps going when the app
// closes; its pid in <project>/render/render.pid), the app follows render/progress.json and
// render/render.log.
#include <QObject>
#include <QProcess>
#include <QTimer>
#include <QUrl>
#include <QVariantMap>

class Studio : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString path READ path NOTIFY changed)
    Q_PROPERTY(QString name READ name NOTIFY changed)
    Q_PROPERTY(QString source READ source NOTIFY changed)          // the Ardour session / stems folder ("" in old projects)
    Q_PROPERTY(bool fromArdour READ fromArdour NOTIFY changed)      // imported from an Ardour session: "Into Ardour" possible
    Q_PROPERTY(QVariantList tracks READ tracks NOTIFY changed)
    Q_PROPERTY(QVariantMap analysis READ analysis NOTIFY changed)
    Q_PROPERTY(double rangeStart READ rangeStart NOTIFY changed)
    Q_PROPERTY(double rangeEnd READ rangeEnd NOTIFY changed)      // 0: to the end
    Q_PROPERTY(QString quality READ quality NOTIFY changed)        // "final" (no buzz) or "draft" (~4x faster category step)
    Q_PROPERTY(QString busy READ busy NOTIFY busyChanged)          // "", "import", "analyse", "reimport", "render", "ardour"
    Q_PROPERTY(QString log READ log NOTIFY logChanged)
    Q_PROPERTY(QVariantMap progress READ progress NOTIFY logChanged)
    Q_PROPERTY(QVariantMap rendered READ rendered NOTIFY changed)  // render/render.json
    Q_PROPERTY(QStringList recent READ recent NOTIFY changed)
    Q_PROPERTY(QStringList chains READ chains CONSTANT)
    Q_PROPERTY(QStringList roles READ roles CONSTANT)
public:
    explicit Studio(const QString &root, QObject *parent = nullptr);
    QString path() const { return m_path; }
    QString name() const { return m_pj.value(QStringLiteral("name")).toString(); }
    QString source() const { return m_pj.value(QStringLiteral("source")).toMap().value(QStringLiteral("path")).toString(); }
    bool fromArdour() const { return m_pj.value(QStringLiteral("source")).toMap().value(QStringLiteral("kind")).toString() == QLatin1String("ardour"); }
    QVariantList tracks() const;
    QVariantMap analysis() const { return m_pj.value(QStringLiteral("analysis")).toMap(); }
    double rangeStart() const { return m_pj.value(QStringLiteral("render")).toMap().value(QStringLiteral("start")).toDouble(); }
    double rangeEnd() const { return m_pj.value(QStringLiteral("render")).toMap().value(QStringLiteral("end")).toDouble(); }
    QString quality() const { return m_pj.value(QStringLiteral("render")).toMap().value(QStringLiteral("quality"), QStringLiteral("final")).toString(); }
    QString busy() const { return m_busy; }
    QString log() const { return m_log; }
    QVariantMap progress() const { return m_progress; }
    QVariantMap rendered() const { return m_rendered; }
    QStringList recent() const;
    QStringList chains() const;
    QStringList roles() const;

    Q_INVOKABLE bool open(const QString &path);
    Q_INVOKABLE void close();
    // source: a folder of WAV stems, or (ardour) an Ardour session folder
    Q_INVOKABLE bool create(const QString &path, const QString &name, const QString &source, bool ardour);
    Q_INVOKABLE bool analyse();
    Q_INVOKABLE bool reimport(const QString &source);   // "" = from where it came; settings kept by track name
    Q_INVOKABLE bool toArdour(bool dryRun = false);     // the ticked rendered tracks into the session (tools/to_ardour.py)
    Q_INVOKABLE void setTrack(const QString &track, const QString &key, const QVariant &value);
    Q_INVOKABLE void setRole(const QStringList &names, const QString &role);   // lead, backing, instrument, keep
    Q_INVOKABLE void setTracks(const QStringList &names, const QString &key, const QVariant &value);   // one save
    Q_INVOKABLE void setRange(double start, double end);
    Q_INVOKABLE void setQuality(const QString &q);
    Q_INVOKABLE QString chainOf(const QString &track) const;      // "auto" resolved
    Q_INVOKABLE bool render(const QStringList &tracks = {});   // none: every track
    Q_INVOKABLE void stopRender();
    Q_INVOKABLE QString renderedFile(const QString &track) const;   // "" when there is none
    Q_INVOKABLE QString originalFile(const QString &track) const;
    Q_INVOKABLE QString renderDir() const { return m_path + QStringLiteral("/render"); }
    Q_INVOKABLE static QString urlToPath(const QUrl &url);
    Q_INVOKABLE static QUrl folderUrl(const QString &path);      // nearest existing folder; empty url when path is ""

signals:
    void changed();
    void busyChanged();
    void logChanged();
    void message(const QString &text);
    void filesChanged();   // a render or re-import finished: the open track's files may be new

private:
    bool save();
    void run(const QString &kind, const QStringList &args, const std::function<void(bool)> &done);
    void poll();
    void migrate();
    void addRecent(const QString &p);
    qint64 renderPid() const;
    QString m_root, m_path, m_busy, m_log;
    QVariantMap m_pj, m_progress, m_rendered;
    QProcess *m_proc = nullptr;
    QTimer m_timer;
};
