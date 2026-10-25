// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "Studio.h"

#include "AppLog.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QSettings>
#include <QUrl>
#include <csignal>
#include <functional>

// chain names and what "auto" means: as tools/render.py (CHAINS, AUTO)
static const QStringList kChains{QStringLiteral("auto"), QStringLiteral("original"), QStringLiteral("neural"),
                                 QStringLiteral("neural_xvoc"), QStringLiteral("novocal"), QStringLiteral("novocal_guided"),
                                 QStringLiteral("novocal_cat"), QStringLiteral("novocal_guided_cat")};
// the roles as the app shows them; stored as role (+ lead) in project.json:
// lead / backing = vocal with lead true / false, keep = left as it is (old projects: line, silent)
// (mixed: same chain as instrument, shown as instrument)
static const QStringList kRoles{QStringLiteral("lead"), QStringLiteral("backing"), QStringLiteral("instrument"),
                                QStringLiteral("keep")};

static QString uiRole(const QVariantMap &t)
{
    const QString r = t.value(QStringLiteral("role")).toString();
    if (r == QLatin1String("vocal"))
        return t.value(QStringLiteral("lead")).toBool() ? QStringLiteral("lead") : QStringLiteral("backing");
    if (r == QLatin1String("instrument") || r == QLatin1String("mixed"))
        return QStringLiteral("instrument");
    return QStringLiteral("keep");
}

Studio::Studio(const QString &root, QObject *parent) : QObject(parent), m_root(root)
{
    m_timer.setInterval(1000);
    connect(&m_timer, &QTimer::timeout, this, &Studio::poll);
}

QStringList Studio::chains() const { return kChains; }
QStringList Studio::roles() const { return kRoles; }

QStringList Studio::recent() const
{
    QStringList out;
    for (const QString &p : QSettings().value(QStringLiteral("product/recent")).toStringList())
        if (QFileInfo::exists(p + QStringLiteral("/project.json")))
            out << p;
    return out;
}

void Studio::addRecent(const QString &p)
{
    QSettings s;
    QStringList r = s.value(QStringLiteral("product/recent")).toStringList();
    r.removeAll(p);
    r.prepend(p);
    s.setValue(QStringLiteral("product/recent"), r.mid(0, 10));
}

QString Studio::urlToPath(const QUrl &url)
{
    return url.isLocalFile() ? url.toLocalFile() : url.toString();
}

QUrl Studio::folderUrl(const QString &path)
{
    if (path.trimmed().isEmpty())
        return {};
    QDir d(QDir::cleanPath(QDir::home().absoluteFilePath(path.trimmed())));
    while (!d.exists() && d.cdUp()) { }   // a new project folder: start in its parent
    return QUrl::fromLocalFile(d.absolutePath());
}

QVariantList Studio::tracks() const
{
    QVariantList out;
    const QVariantMap t = m_pj.value(QStringLiteral("tracks")).toMap();
    for (auto it = t.begin(); it != t.end(); ++it) {
        QVariantMap m = it.value().toMap();
        m[QStringLiteral("name")] = it.key();
        m[QStringLiteral("ui_role")] = uiRole(m);
        m[QStringLiteral("resolved")] = chainOf(it.key());
        m[QStringLiteral("rendered")] = !renderedFile(it.key()).isEmpty();
        if (!m.contains(QStringLiteral("to_ardour")))       // default: the ones that are cleaned
            m[QStringLiteral("to_ardour")] = m[QStringLiteral("resolved")].toString() != QLatin1String("original");
        out << m;
    }
    return out;
}

QString Studio::chainOf(const QString &track) const
{
    const QVariantMap t = m_pj.value(QStringLiteral("tracks")).toMap().value(track).toMap();
    const QString c = t.value(QStringLiteral("chain"), QStringLiteral("auto")).toString();
    if (c != QLatin1String("auto"))
        return c;
    const QString role = t.value(QStringLiteral("role")).toString();
    if (role == QLatin1String("vocal"))
        return t.value(QStringLiteral("lead")).toBool() ? QStringLiteral("neural") : QStringLiteral("neural_xvoc");
    if (role == QLatin1String("instrument") || role == QLatin1String("mixed"))
        return QStringLiteral("novocal_guided_cat");
    return QStringLiteral("original");
}

bool Studio::open(const QString &path)
{
    QFile f(path + QStringLiteral("/project.json"));
    if (!f.open(QIODevice::ReadOnly)) {
        emit message(QStringLiteral("no project in %1").arg(path));
        return false;
    }
    m_pj = QJsonDocument::fromJson(f.readAll()).object().toVariantMap();
    m_path = QDir(path).absolutePath();
    migrate();
    m_rendered.clear();
    QFile r(renderDir() + QStringLiteral("/render.json"));
    if (r.open(QIODevice::ReadOnly))
        m_rendered = QJsonDocument::fromJson(r.readAll()).object().toVariantMap();
    addRecent(m_path);
    logInfo(QStringLiteral("product: opened %1 (%2 tracks)").arg(m_path).arg(m_pj.value(QStringLiteral("tracks")).toMap().size()));
    m_log.clear();
    m_progress.clear();
    if (renderPid() > 0 && m_busy.isEmpty()) {   // a render still running from before
        m_busy = QStringLiteral("render");
        emit busyChanged();
    }
    poll();
    m_timer.start();
    emit changed();
    return true;
}

// older projects: "line" / "silent" -> "keep"; the roles of an analysed project count as the
// user's (they may have changed them, and nothing recorded which), so "Suggest roles" keeps them
void Studio::migrate()
{
    QVariantMap tr = m_pj.value(QStringLiteral("tracks")).toMap();
    const bool analysed = m_pj.value(QStringLiteral("analysis")).toMap().value(QStringLiteral("done")).toBool();
    bool any = false, flagged = false;
    for (auto it = tr.begin(); it != tr.end(); ++it)
        flagged |= it.value().toMap().contains(QStringLiteral("role_set"));
    for (auto it = tr.begin(); it != tr.end(); ++it) {
        QVariantMap t = it.value().toMap();
        const QString r = t.value(QStringLiteral("role")).toString();
        if (r == QLatin1String("line") || r == QLatin1String("silent")) {
            t[QStringLiteral("role")] = QStringLiteral("keep");
            any = true;
        }
        if (analysed && !flagged) {
            t[QStringLiteral("role_set")] = true;
            any = true;
        }
        it.value() = t;
    }
    if (any) {
        m_pj[QStringLiteral("tracks")] = tr;
        save();
    }
}

void Studio::close()
{
    m_timer.stop();
    m_path.clear();
    m_pj.clear();
    m_rendered.clear();
    m_log.clear();
    emit changed();
    emit logChanged();
}

bool Studio::save()
{
    QSaveFile f(m_path + QStringLiteral("/project.json"));
    if (!f.open(QIODevice::WriteOnly))
        return false;
    f.write(QJsonDocument(QJsonObject::fromVariantMap(m_pj)).toJson(QJsonDocument::Indented));
    return f.commit();
}

void Studio::run(const QString &kind, const QStringList &args, const std::function<void(bool)> &done)
{
    m_busy = kind;
    m_log = QStringLiteral("%1 …\n").arg(kind);
    emit busyChanged();
    emit logChanged();
    m_proc = new QProcess(this);
    m_proc->setWorkingDirectory(m_root);
    m_proc->setProcessChannelMode(QProcess::MergedChannels);
    connect(m_proc, &QProcess::readyRead, this, [this] {
        for (const QString &l : QString::fromUtf8(m_proc->readAll()).split(QLatin1Char('\n')))
            if (!l.trimmed().isEmpty() && !l.contains(QLatin1String("Warning")) && !l.contains(QLatin1String("warn("))) {
                m_log += l + QLatin1Char('\n');
                logInfo(QStringLiteral("product: ") + l);      // also in work/logs/app.<host>.log
            }
        if (m_log.size() > 20000)
            m_log = m_log.right(20000);
        emit logChanged();
    });
    connect(m_proc, &QProcess::finished, this, [this, kind, done](int code, QProcess::ExitStatus) {
        logInfo(QStringLiteral("product: %1 finished (%2)").arg(kind).arg(code));
        m_proc->deleteLater();
        m_proc = nullptr;
        m_busy.clear();
        emit busyChanged();
        done(code == 0);
    });
    m_proc->start(QStringLiteral("python3"), args);
}

bool Studio::create(const QString &path, const QString &name, const QString &source, bool ardour)
{
    if (!m_busy.isEmpty() || path.isEmpty() || name.trimmed().isEmpty() || source.isEmpty())
        return false;
    if (QFileInfo::exists(path + QStringLiteral("/project.json"))) {
        emit message(QStringLiteral("%1 is a project already: open it").arg(path));
        return false;
    }
    run(QStringLiteral("import"), {QStringLiteral("tools/project.py"), QStringLiteral("new"), path, QStringLiteral("--name"), name.trimmed(),
                                   ardour ? QStringLiteral("--ardour") : QStringLiteral("--stems"), source},
        [this, path](bool ok) {
            if (ok && open(path))
                emit message(QStringLiteral("imported: now Analyse"));
            else
                emit message(QStringLiteral("the import failed (see the log)"));
        });
    return true;
}

bool Studio::analyse()
{
    if (!m_busy.isEmpty() || m_path.isEmpty())
        return false;
    run(QStringLiteral("analyse"), {QStringLiteral("tools/project.py"), QStringLiteral("analyse"), m_path}, [this](bool ok) {
        const QString p = m_path;
        open(p);
        emit message(ok ? QStringLiteral("roles suggested (the ones you set are kept)") : QStringLiteral("the suggestion failed (see the log)"));
    });
    return true;
}

bool Studio::reimport(const QString &source)
{
    if (!m_busy.isEmpty() || m_path.isEmpty() || renderPid() > 0)
        return false;
    QStringList args{QStringLiteral("tools/project.py"), QStringLiteral("reimport"), m_path};
    if (!source.isEmpty())
        args << QStringLiteral("--source") << source;
    run(QStringLiteral("reimport"), args, [this](bool ok) {
        const QString p = m_path;
        open(p);                     // the summary (renamed / new / gone tracks) is in render.log: the log panel
        emit filesChanged();
        emit message(ok ? QStringLiteral("re-imported: check the new tracks, then Render") : QStringLiteral("the re-import failed (see the log)"));
    });
    return true;
}

bool Studio::toArdour(bool dryRun)
{
    if (!m_busy.isEmpty() || m_path.isEmpty() || renderPid() > 0 || !fromArdour())
        return false;
    QStringList args{QStringLiteral("tools/to_ardour.py"), m_path};
    if (dryRun)
        args << QStringLiteral("--dry-run");
    run(QStringLiteral("ardour"), args, [this, dryRun](bool ok) {
        const QString p = m_path;
        open(p);                     // project.json notes the Cleaned tracks it made
        if (!dryRun)
            emit message(ok ? QStringLiteral("in Ardour: open the session") : QStringLiteral("into Ardour failed (see the log)"));
    });
    return true;
}

void Studio::setTrack(const QString &track, const QString &key, const QVariant &value)
{
    setTracks({track}, key, value);
}

void Studio::setTracks(const QStringList &names, const QString &key, const QVariant &value)
{
    // several lead mics are fine (two lead singers): render.py hands them all to vocal_xleak
    QVariantMap tr = m_pj.value(QStringLiteral("tracks")).toMap();
    bool any = false;
    for (const QString &n : names) {
        if (!tr.contains(n))
            continue;
        QVariantMap t = tr.value(n).toMap();
        t[key] = value;
        tr[n] = t;
        any = true;
    }
    if (!any)
        return;
    m_pj[QStringLiteral("tracks")] = tr;
    save();
    emit changed();
}

void Studio::setRole(const QStringList &names, const QString &role)
{
    if (!kRoles.contains(role))
        return;
    QVariantMap tr = m_pj.value(QStringLiteral("tracks")).toMap();
    for (const QString &n : names) {
        if (!tr.contains(n))
            continue;
        QVariantMap t = tr.value(n).toMap();
        const bool voc = role == QLatin1String("lead") || role == QLatin1String("backing");
        t[QStringLiteral("role")] = voc ? QStringLiteral("vocal") : role;
        t[QStringLiteral("lead")] = role == QLatin1String("lead");
        t[QStringLiteral("role_set")] = true;    // "Suggest roles" leaves it alone
        tr[n] = t;
    }
    m_pj[QStringLiteral("tracks")] = tr;
    save();
    emit changed();
}

void Studio::setRange(double start, double end)
{
    QVariantMap r = m_pj.value(QStringLiteral("render")).toMap();
    r[QStringLiteral("start")] = qMax(0.0, start);
    r[QStringLiteral("end")] = end > start ? QVariant(end) : QVariant();
    m_pj[QStringLiteral("render")] = r;
    save();
    emit changed();
}

void Studio::setQuality(const QString &q)
{
    QVariantMap r = m_pj.value(QStringLiteral("render")).toMap();
    r[QStringLiteral("quality")] = q == QLatin1String("draft") ? q : QStringLiteral("final");
    m_pj[QStringLiteral("render")] = r;
    save();
    emit changed();
}

qint64 Studio::renderPid() const
{
    QFile f(renderDir() + QStringLiteral("/render.pid"));
    if (m_path.isEmpty() || !f.open(QIODevice::ReadOnly))
        return 0;
    const qint64 pid = f.readAll().trimmed().toLongLong();
    // still running, and still our render?
    QFile cmd(QStringLiteral("/proc/%1/cmdline").arg(pid));
    if (pid <= 0 || !cmd.open(QIODevice::ReadOnly) || !cmd.readAll().contains("render.py"))
        return 0;
    return pid;
}

bool Studio::render(const QStringList &tracks)
{
    if (!m_busy.isEmpty() || m_path.isEmpty())
        return false;
    QDir().mkpath(renderDir());
    // detached (setsid): it goes on when the app closes; output into render/render.log
    // ($1 the app's root, $2 the project, then --track NAME ... for some tracks only)
    const QString sh = QStringLiteral("cd \"$1\" || exit 1; p=\"$2\"; shift 2; "
                                      "setsid nohup python3 tools/render.py \"$p\" \"$@\" >> \"$p/render/render.out\" 2>&1 < /dev/null & "
                                      "echo $! > \"$p/render/render.pid\"");
    QStringList args{QStringLiteral("-c"), sh, QStringLiteral("sh"), m_root, m_path};
    for (const QString &t : tracks)
        args << QStringLiteral("--track") << t;
    const bool ok = QProcess::execute(QStringLiteral("sh"), args) == 0;
    if (ok) {
        m_busy = QStringLiteral("render");
        emit busyChanged();
        logInfo(QStringLiteral("product: render started for %1").arg(m_path));
    }
    return ok;
}

void Studio::stopRender()
{
    const qint64 pid = renderPid();
    if (pid > 0) {
        ::kill(-pid_t(pid), SIGTERM);     // the whole group (render.py and the tool it runs)
        ::kill(pid_t(pid), SIGTERM);
        logInfo(QStringLiteral("product: render stopped"));
        m_log += QStringLiteral("stopped (finished segments are kept: Render goes on from there)\n");
        emit logChanged();
    }
}

void Studio::poll()
{
    if (m_path.isEmpty())
        return;
    if (m_busy == QLatin1String("render") || m_busy.isEmpty()) {
        QFile p(renderDir() + QStringLiteral("/progress.json"));
        if (p.open(QIODevice::ReadOnly))
            m_progress = QJsonDocument::fromJson(p.readAll()).object().toVariantMap();
        QFile l(renderDir() + QStringLiteral("/render.log"));
        if (l.open(QIODevice::ReadOnly)) {
            if (l.size() > 20000)
                l.seek(l.size() - 20000);
            m_log = QString::fromUtf8(l.readAll());
        }
        emit logChanged();
        if (m_busy == QLatin1String("render") && renderPid() == 0) {
            m_busy.clear();
            emit busyChanged();
            const QString path = m_path;
            open(path);           // the new render.json and files
            emit filesChanged();
            emit message(m_log.contains(QLatin1String("DONE")) ? QStringLiteral("render finished") : QStringLiteral("render stopped"));
        }
    }
}

QString Studio::renderedFile(const QString &track) const
{
    const QString p = renderDir() + QLatin1Char('/') + track + QStringLiteral(".wav");
    return QFileInfo::exists(p) ? p : QString();
}

QString Studio::originalFile(const QString &track) const
{
    return m_pj.value(QStringLiteral("tracks")).toMap().value(track).toMap().value(QStringLiteral("file")).toString();
}
