// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "Markers.h"

#include "AppLog.h"
#include "AudioFile.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <cmath>
#include <functional>

static QVariantMap passage(double s, double e, const QString &k, bool autoTag = false)
{
    return {{QStringLiteral("start"), s}, {QStringLiteral("end"), e}, {QStringLiteral("kind"), k},
            {QStringLiteral("auto"), autoTag}};
}

static double st(const QVariant &v) { return v.toMap().value(QStringLiteral("start")).toDouble(); }
static double en(const QVariant &v) { return v.toMap().value(QStringLiteral("end")).toDouble(); }
static QString kd(const QVariant &v) { return v.toMap().value(QStringLiteral("kind")).toString(); }
static bool au(const QVariant &v) { return v.toMap().value(QStringLiteral("auto")).toBool(); }

// sorted, no overlaps (a later one starts where the earlier ends), none shorter than 50 ms,
// touching passages of the same tag and origin joined
static QVariantList tidy(QVariantList l)
{
    std::sort(l.begin(), l.end(), [](const QVariant &a, const QVariant &b) { return st(a) < st(b); });
    for (int i = 1; i < l.size(); ++i)
        if (st(l[i]) < en(l[i - 1]))
            l[i - 1] = passage(st(l[i - 1]), st(l[i]), kd(l[i - 1]), au(l[i - 1]));
    for (int i = l.size() - 1; i >= 0; --i)
        if (en(l[i]) - st(l[i]) < 0.05)
            l.removeAt(i);
    for (int i = l.size() - 1; i > 0; --i)
        if (kd(l[i - 1]) == kd(l[i]) && au(l[i - 1]) == au(l[i]) && st(l[i]) - en(l[i - 1]) < 1e-6) {
            l[i - 1] = passage(st(l[i - 1]), en(l[i]), kd(l[i]), au(l[i]));
            l.removeAt(i);
        }
    return l;
}

Markers::Markers(const QString &root, QObject *parent) : QObject(parent), m_root(root) {}

QString Markers::concert() const
{
    return m_folder.section(QLatin1Char('/'), 0, 0);
}

void Markers::snapshot()
{
    m_undo << QVariantMap{{QStringLiteral("all"), m_all}, {QStringLiteral("defs"), m_defs}};
    if (m_undo.size() > 200)
        m_undo.removeFirst();
    m_redo.clear();
}

void Markers::touch()
{
    m_dirty = true;
    emit changed();
}

void Markers::put(const QString &t, QVariantList l)
{
    m_all[t] = tidy(l);
}

void Markers::undo()
{
    if (m_undo.isEmpty())
        return;
    m_redo << QVariantMap{{QStringLiteral("all"), m_all}, {QStringLiteral("defs"), m_defs}};
    const QVariantMap s = m_undo.takeLast();
    m_all = s.value(QStringLiteral("all")).toMap();
    m_defs = s.value(QStringLiteral("defs")).toMap();
    logInfo(QStringLiteral("tags: undo"));
    touch();
}

void Markers::redo()
{
    if (m_redo.isEmpty())
        return;
    m_undo << QVariantMap{{QStringLiteral("all"), m_all}, {QStringLiteral("defs"), m_defs}};
    const QVariantMap s = m_redo.takeLast();
    m_all = s.value(QStringLiteral("all")).toMap();
    m_defs = s.value(QStringLiteral("defs")).toMap();
    logInfo(QStringLiteral("tags: redo"));
    touch();
}

void Markers::begin()
{
    snapshot();
}

void Markers::setTrack(const QString &t)
{
    if (t == m_track)
        return;
    m_track = t;
    emit changed();
}

void Markers::readTags()
{
    m_all.clear();
    QFile f(m_root + QStringLiteral("/output/songs/") + m_folder + QStringLiteral("tags.json"));
    if (!f.open(QIODevice::ReadOnly))
        return;
    const QJsonObject tr = QJsonDocument::fromJson(f.readAll()).object().value(QLatin1String("tracks")).toObject();
    for (auto it = tr.begin(); it != tr.end(); ++it) {
        QVariantList l;
        for (const QJsonValue &v : it.value().toArray()) {
            const QJsonArray a = v.toArray();
            l << passage(a[0].toDouble(), a[1].toDouble(), a[2].toString(), a.size() > 3 && a[3].toInt() != 0);
        }
        m_all[it.key()] = tidy(l);
    }
}

void Markers::loadSong(const QString &folder)
{
    m_folder = folder;
    m_undo.clear();
    m_redo.clear();
    m_dirty = false;
    m_defs.clear();
    QFile d(m_root + QStringLiteral("/output/songs/") + concert() + QStringLiteral("/tracks.json"));
    if (d.open(QIODevice::ReadOnly))
        m_defs = QJsonDocument::fromJson(d.readAll()).object().value(QLatin1String("tracks")).toObject().toVariantMap();
    readTags();
    int n = 0;
    for (const QVariant &v : m_all)
        n += v.toList().size();
    logInfo(QStringLiteral("tags %1: %2 tracks defined, %3 passages").arg(folder).arg(m_defs.size()).arg(n));
    emit changed();
}

QStringList Markers::tagsOf(const QString &track) const
{
    return m_defs.value(track).toMap().value(QStringLiteral("tags")).toStringList();
}

bool Markers::splitOf(const QString &track) const
{
    return m_defs.value(track).toMap().value(QStringLiteral("split")).toBool();
}

void Markers::setSplit(const QString &track, bool on)
{
    if (track.isEmpty() || splitOf(track) == on)
        return;
    snapshot();
    QVariantMap d = m_defs.value(track).toMap();
    d[QStringLiteral("split")] = on;
    m_defs[track] = d;
    logInfo(QStringLiteral("tags: %1 split %2").arg(track, on ? QStringLiteral("on") : QStringLiteral("off")));
    touch();
}

bool Markers::addTag(const QString &track, const QString &name)
{
    const QString n = name.trimmed();
    if (track.isEmpty() || n.isEmpty() || n == QLatin1String("rest") || tagsOf(track).contains(n)
        || n.contains(QRegularExpression(QStringLiteral("[/\\\\:\\t]"))))
        return false;
    snapshot();
    QVariantMap d = m_defs.value(track).toMap();
    d[QStringLiteral("tags")] = tagsOf(track) << n;
    if (!d.contains(QStringLiteral("split")))
        d[QStringLiteral("split")] = true;      // a track gets tags to be split
    m_defs[track] = d;
    logInfo(QStringLiteral("tags: %1 + %2").arg(track, n));
    touch();
    return true;
}

bool Markers::renameTag(const QString &track, const QString &from, const QString &to)
{
    const QString n = to.trimmed();
    QStringList tags = tagsOf(track);
    const int i = tags.indexOf(from);
    if (i < 0 || n.isEmpty() || n == from || n == QLatin1String("rest") || tags.contains(n)
        || n.contains(QRegularExpression(QStringLiteral("[/\\\\:\\t]"))))
        return false;
    snapshot();
    tags[i] = n;
    QVariantMap d = m_defs.value(track).toMap();
    d[QStringLiteral("tags")] = tags;
    m_defs[track] = d;
    QVariantList l = list(track);
    for (QVariant &v : l)
        if (kd(v) == from)
            v = passage(st(v), en(v), n, au(v));
    put(track, l);
    logInfo(QStringLiteral("tags: %1 %2 -> %3").arg(track, from, n));
    touch();
    return true;
}

void Markers::removeTag(const QString &track, const QString &name)
{
    QStringList tags = tagsOf(track);
    if (!tags.contains(name))
        return;
    snapshot();
    tags.removeAll(name);
    QVariantMap d = m_defs.value(track).toMap();
    d[QStringLiteral("tags")] = tags;
    m_defs[track] = d;
    QVariantList l = list(track);
    for (int i = l.size() - 1; i >= 0; --i)
        if (kd(l[i]) == name)
            l.removeAt(i);
    put(track, l);
    logInfo(QStringLiteral("tags: %1 - %2").arg(track, name));
    touch();
}

void Markers::paint(const QString &t, double start, double end, const QString &kind)
{
    // [start, end) becomes kind (the user's); what was there is cut out
    QVariantList out;
    for (const QVariant &v : list(t)) {
        if (en(v) <= start || st(v) >= end) {
            out << v;
            continue;
        }
        if (st(v) < start)
            out << passage(st(v), start, kd(v), au(v));
        if (en(v) > end)
            out << passage(end, en(v), kd(v), au(v));
    }
    if (!kind.isEmpty())
        out << passage(start, end, kind);
    put(t, out);
}

void Markers::add(double start, double end, const QString &kind)
{
    addTo({m_track}, start, end, kind);
}

void Markers::addTo(const QStringList &tracks, double start, double end, const QString &kind)
{
    if (end < start)
        std::swap(start, end);
    QStringList use;
    for (const QString &t : tracks)
        if (!use.contains(t) && tagsOf(t).contains(kind))
            use << t;
    if (end - start < 0.05 || use.isEmpty())
        return;
    snapshot();
    for (const QString &t : use)
        paint(t, start, end, kind);
    logInfo(QStringLiteral("tag %1 %2-%3 on %4").arg(kind).arg(start, 0, 'f', 2).arg(end, 0, 'f', 2).arg(use.join(QLatin1Char(' '))));
    touch();
}

void Markers::clearRange(double start, double end)
{
    if (end < start)
        std::swap(start, end);
    if (within(start, end).isEmpty())
        return;
    snapshot();
    paint(m_track, start, end, QString());
    logInfo(QStringLiteral("tags cleared %1-%2 on %3").arg(start, 0, 'f', 2).arg(end, 0, 'f', 2).arg(m_track));
    touch();
}

QVariantList Markers::within(double start, double end) const
{
    QVariantList out;
    const QVariantList l = passages();
    for (int i = 0; i < l.size(); ++i)
        if (en(l[i]) > start && st(l[i]) < end)
            out << i;
    return out;
}

void Markers::removeMany(const QVariantList &indices)
{
    QVariantList l = passages();
    QList<int> idx;
    for (const QVariant &v : indices)
        if (v.toInt() >= 0 && v.toInt() < l.size() && !idx.contains(v.toInt()))
            idx << v.toInt();
    if (idx.isEmpty())
        return;
    snapshot();
    std::sort(idx.begin(), idx.end(), std::greater<int>());
    for (int i : idx)
        l.removeAt(i);
    put(m_track, l);
    logInfo(QStringLiteral("tags removed %1 on %2").arg(idx.size()).arg(m_track));
    touch();
}

void Markers::setKindMany(const QVariantList &indices, const QString &kind)
{
    if (!tagsOf(m_track).contains(kind))
        return;
    QVariantList l = passages();
    bool any = false;
    for (const QVariant &v : indices) {
        const int i = v.toInt();
        if (i < 0 || i >= l.size())
            continue;
        if (!any)
            snapshot();
        any = true;
        l[i] = passage(st(l[i]), en(l[i]), kind);
    }
    if (!any)
        return;
    put(m_track, l);
    logInfo(QStringLiteral("tags %1 -> %2 on %3").arg(indices.size()).arg(kind, m_track));
    touch();
}

void Markers::setKind(int i, const QString &kind)
{
    setKindMany({i}, kind);
}

int Markers::edge(int i, int which, double t)
{
    QVariantList l = passages();
    const double s = st(l[i]), e = en(l[i]);
    // between the neighbours and at least 50 ms long
    const double lo = i > 0 ? en(l[i - 1]) : 0.0;
    const double hi = i + 1 < l.size() ? st(l[i + 1]) : 1e9;
    if (which == 0)
        l[i] = passage(qBound(lo, t, e - 0.05), e, kd(l[i]));
    else
        l[i] = passage(s, qBound(s + 0.05, t, hi), kd(l[i]));
    m_all[m_track] = l;      // no tidy: the indices stay while dragging
    touch();
    return i;
}

int Markers::setEdge(int i, int which, double t)
{
    if (i < 0 || i >= passages().size())
        return -1;
    snapshot();
    logInfo(QStringLiteral("tag %1 %2 -> %3").arg(i).arg(which ? QStringLiteral("end") : QStringLiteral("start")).arg(t, 0, 'f', 3));
    return edge(i, which, t);
}

int Markers::dragEdge(int i, int which, double t)
{
    if (i < 0 || i >= passages().size())
        return -1;
    return edge(i, which, t);
}

void Markers::remove(int i)
{
    removeMany({i});
}

void Markers::move(int i, double start, double end)
{
    QVariantList l = passages();
    if (i < 0 || i >= l.size())
        return;
    if (end < start)
        std::swap(start, end);
    if (end - start < 0.05)
        return;
    const QString k = kd(l[i]);
    snapshot();
    l.removeAt(i);
    m_all[m_track] = l;
    paint(m_track, start, end, k);
    logInfo(QStringLiteral("tag %1 moved to %2-%3").arg(i).arg(start, 0, 'f', 2).arg(end, 0, 'f', 2));
    touch();
}

int Markers::at(double t) const
{
    const QVariantList l = passages();
    for (int i = 0; i < l.size(); ++i)
        if (t >= st(l[i]) && t < en(l[i]))
            return i;
    return -1;
}

void Markers::acceptAuto(const QStringList &tracks)
{
    snapshot();
    for (const QString &t : tracks) {
        QVariantList l = list(t);
        for (QVariant &v : l)
            v = passage(st(v), en(v), kd(v));
        put(t, l);
    }
    touch();
}

void Markers::clearAuto(const QStringList &tracks)
{
    snapshot();
    for (const QString &t : tracks) {
        QVariantList l = list(t);
        for (int i = l.size() - 1; i >= 0; --i)
            if (au(l[i]))
                l.removeAt(i);
        put(t, l);
    }
    touch();
}

bool Markers::save()
{
    if (m_folder.isEmpty())
        return false;
    const QString stamp = QDateTime::currentDateTimeUtc().toString(Qt::ISODate);
    QJsonObject tr;
    for (auto it = m_all.begin(); it != m_all.end(); ++it) {
        QJsonArray a;
        for (const QVariant &v : it.value().toList())
            a.append(QJsonArray{std::round(st(v) * 1000) / 1000, std::round(en(v) * 1000) / 1000, kd(v), au(v) ? 1 : 0});
        if (!a.isEmpty())
            tr[it.key()] = a;
    }
    QSaveFile f(m_root + QStringLiteral("/output/songs/") + m_folder + QStringLiteral("tags.json"));
    QSaveFile d(m_root + QStringLiteral("/output/songs/") + concert() + QStringLiteral("/tracks.json"));
    bool ok = f.open(QIODevice::WriteOnly) && d.open(QIODevice::WriteOnly);
    if (ok) {
        f.write(QJsonDocument(QJsonObject{{QStringLiteral("tracks"), tr}, {QStringLiteral("edited"), stamp},
                                          {QStringLiteral("note"), QStringLiteral("per track: [start, end, tag, auto] in seconds of the listening part; "
                                                                                  "auto 1 = proposed by tools/autotag.py")}})
                    .toJson(QJsonDocument::Indented));
        d.write(QJsonDocument(QJsonObject{{QStringLiteral("tracks"), QJsonObject::fromVariantMap(m_defs)}, {QStringLiteral("edited"), stamp},
                                          {QStringLiteral("note"), QStringLiteral("per track: split flag and tag names, for the whole concert")}})
                    .toJson(QJsonDocument::Indented));
        ok = f.commit() && d.commit();
    }
    if (ok)
        m_dirty = false;
    logInfo(QStringLiteral("tags %1 %2").arg(m_folder, ok ? QStringLiteral("saved") : QStringLiteral("NOT saved")));
    emit changed();
    return ok;
}

bool Markers::autocomplete(const QStringList &tracks)
{
    if (m_proc || tracks.isEmpty() || !save())
        return false;
    m_proc = new QProcess(this);
    m_proc->setWorkingDirectory(m_root);
    m_proc->setProcessChannelMode(QProcess::MergedChannels);
    const QStringList args{QStringLiteral("tools/autotag.py"), m_root + QStringLiteral("/output/songs/") + m_folder,
                           QStringLiteral("--tracks"), tracks.join(QLatin1Char(','))};
    connect(m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        m_report = QString::fromUtf8(m_proc->readAll()).trimmed();
        logInfo(QStringLiteral("autotag (exit %1): %2").arg(code).arg(m_report));
        m_proc->deleteLater();
        m_proc = nullptr;
        if (code == 0) {
            snapshot();          // undo goes back to before the proposals
            readTags();
            m_dirty = false;
            emit changed();
        }
        emit busyChanged();
    });
    m_report.clear();
    m_proc->start(QStringLiteral("python3"), args);
    logInfo(QStringLiteral("autotag started: %1").arg(tracks.join(QLatin1Char(' '))));
    emit busyChanged();
    return true;
}

QString Markers::split(const QString &track, const QString &trackKey, const QString &source, bool withRest)
{
    const QStringList tags = tagsOf(track);
    if (tags.isEmpty())
        return QStringLiteral("%1 has no tags").arg(track);
    Audio a = readMono(source);
    if (!a.error.isEmpty())
        return a.error;
    const size_t n = a.data.size();
    // weight per file (one per tag, then the rest): 1 inside its passages, raised-cosine fades
    // of 10 ms at the edges; all files change at the same places, so they add up to the source
    const int F = int(tags.size()) + 1;
    std::vector<std::vector<float>> w(size_t(F), std::vector<float>(n, 0.0f));
    std::fill(w[size_t(F - 1)].begin(), w[size_t(F - 1)].end(), 1.0f);
    for (const QVariant &v : list(track)) {
        const int f = int(tags.indexOf(kd(v)));
        if (f < 0)
            continue;
        const size_t s = size_t(std::max(0.0, st(v)) * a.rate);
        const size_t e = std::min(n, size_t(en(v) * a.rate));
        for (size_t i = s; i < e; ++i) {
            w[size_t(f)][i] = 1.0f;
            w[size_t(F - 1)][i] = 0.0f;
        }
    }
    const long L = std::max(2, a.rate / 100);
    for (auto &ww : w) {
        const std::vector<float> step = ww;
        for (size_t t = 1; t < n; ++t) {
            if (step[t] == step[t - 1])
                continue;
            const float from = step[t - 1], to = step[t];
            for (long j = -L / 2; j < L / 2; ++j) {
                const long k = long(t) + j;
                if (k < 0 || size_t(k) >= n)
                    continue;
                const float r = 0.5f - 0.5f * std::cos(float(M_PI) * (j + L / 2 + 0.5f) / float(L));
                ww[size_t(k)] = from + (to - from) * r;
            }
        }
    }
    const QStringList p = trackKey.split(QLatin1Char('/'));
    const QString dir = m_root + QStringLiteral("/output/split/") + p.mid(0, p.size() - 1).join(QLatin1Char('/'));
    QDir().mkpath(dir);
    QStringList written;
    std::vector<float> y(n);
    for (int f = 0; f < F; ++f) {
        if (f == F - 1 && !withRest)
            continue;
        for (size_t i = 0; i < n; ++i)
            y[i] = a.data[i] * w[size_t(f)][i];
        const QString name = f == F - 1 ? QStringLiteral("rest") : QString(tags[f]).replace(QLatin1Char(' '), QLatin1Char('_'));
        const QString out = dir + QLatin1Char('/') + p.last() + QLatin1Char('.') + name + QStringLiteral(".wav");
        const QString err = writeMonoFloat(out, y.data(), n, a.rate);
        if (!err.isEmpty())
            return err;
        written << QDir(m_root).relativeFilePath(out);
    }
    logInfo(QStringLiteral("split %1 from %2: %3").arg(trackKey, QFileInfo(source).fileName(), written.join(QStringLiteral(", "))));
    return written.join(QLatin1Char('\n'));
}
