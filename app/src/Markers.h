// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// Tags: the user's own labels per track, to split a track into one file per tag (e.g. lead /
// coro on a vocal mic, bongo / bell or guiro / maracas on one mic): a flag for splitting a
// track and names for its tags; mark some places where each tag plays, autocomplete, revise.
//   output/songs/<concert>/tracks.json        per track: split flag and tag names (whole concert)
//   output/songs/<concert>/<song>/tags.json   per track: passages [start, end, tag, auto], seconds
//                                             of the listening part; auto = proposed by autocomplete
// Passages of one track don't overlap. The editing calls work on the active track (`track`);
// a passage the user makes or touches is theirs (auto false). Autocomplete
// learns from the user's passages and fills the rest with auto ones.
// Split: a track into full-length files <track>.<tag>.wav and <track>.rest.wav (10 ms fades;
// they add up to the source), for gates and sidechains in the DAW.
#include <QObject>
#include <QProcess>
#include <QVariantList>

class Markers : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString track READ track WRITE setTrack NOTIFY changed)
    Q_PROPERTY(QVariantList passages READ passages NOTIFY changed)   // of the active track
    Q_PROPERTY(QVariantMap all READ all NOTIFY changed)              // track -> passages
    Q_PROPERTY(QVariantMap defs READ defs NOTIFY changed)            // track -> {split, tags}
    Q_PROPERTY(QStringList kinds READ kinds NOTIFY changed)          // tags of the active track
    Q_PROPERTY(bool dirty READ dirty NOTIFY changed)
    Q_PROPERTY(QString folder READ folder NOTIFY changed)
    Q_PROPERTY(bool canUndo READ canUndo NOTIFY changed)
    Q_PROPERTY(bool canRedo READ canRedo NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)               // autocomplete running
    Q_PROPERTY(QString report READ report NOTIFY busyChanged)        // its last output
public:
    explicit Markers(const QString &root, QObject *parent = nullptr);
    QString track() const { return m_track; }
    void setTrack(const QString &t);
    QVariantList passages() const { return m_all.value(m_track).toList(); }
    QVariantMap all() const { return m_all; }
    QVariantMap defs() const { return m_defs; }
    QStringList kinds() const { return tagsOf(m_track); }
    bool dirty() const { return m_dirty; }
    QString folder() const { return m_folder; }
    bool canUndo() const { return !m_undo.isEmpty(); }
    bool canRedo() const { return !m_redo.isEmpty(); }
    bool busy() const { return m_proc != nullptr; }
    QString report() const { return m_report; }

    // folder: "<concert>/<song folder>/"
    Q_INVOKABLE void loadSong(const QString &folder);

    // tracks: split flag and tag names (concert-wide; renaming or removing a tag changes its passages in this song)
    Q_INVOKABLE QStringList tagsOf(const QString &track) const;
    Q_INVOKABLE bool splitOf(const QString &track) const;
    Q_INVOKABLE void setSplit(const QString &track, bool on);
    Q_INVOKABLE bool addTag(const QString &track, const QString &name);
    Q_INVOKABLE bool renameTag(const QString &track, const QString &from, const QString &to);
    Q_INVOKABLE void removeTag(const QString &track, const QString &name);

    // every edit can be undone; all on the active track unless tracks are named
    Q_INVOKABLE void add(double start, double end, const QString &kind);   // replaces what was there
    Q_INVOKABLE void addTo(const QStringList &tracks, double start, double end, const QString &kind);   // where the track has the tag
    Q_INVOKABLE void clearRange(double start, double end);                 // cuts [start, end) out
    Q_INVOKABLE void removeMany(const QVariantList &indices);
    Q_INVOKABLE void setKindMany(const QVariantList &indices, const QString &kind);
    // one edge of passage i (which 0: start, 1: end), kept between its neighbours; returns i's new index
    Q_INVOKABLE int setEdge(int i, int which, double t);
    // drag gestures: begin() once, then dragEdge(...) many times; one undo step
    Q_INVOKABLE void begin();
    Q_INVOKABLE int dragEdge(int i, int which, double t);
    Q_INVOKABLE void undo();
    Q_INVOKABLE void redo();
    Q_INVOKABLE QVariantList within(double start, double end) const;   // indices overlapping [start, end)
    Q_INVOKABLE void remove(int i);
    Q_INVOKABLE void setKind(int i, const QString &kind);
    // passage i to [start, end): its old place is cleared, it replaces what is at the new place
    Q_INVOKABLE void move(int i, double start, double end);
    Q_INVOKABLE int at(double t) const;          // index of the passage at t, or -1
    Q_INVOKABLE void acceptAuto(const QStringList &tracks);   // the proposals become the user's
    Q_INVOKABLE void clearAuto(const QStringList &tracks);
    Q_INVOKABLE bool save();

    // tools/autotag.py on these tracks (saves first); busy until it is done, then the proposals are loaded
    Q_INVOKABLE bool autocomplete(const QStringList &tracks);
    // writes the split files of a track; source: absolute path of the file to split
    // (original or a version); returns the written paths or an error text
    Q_INVOKABLE QString split(const QString &track, const QString &trackKey, const QString &source, bool withRest);

signals:
    void changed();
    void busyChanged();

private:
    void snapshot();
    void touch();
    QVariantList list(const QString &t) const { return m_all.value(t).toList(); }
    void put(const QString &t, QVariantList l);
    void paint(const QString &t, double start, double end, const QString &kind);
    int edge(int i, int which, double t);
    void readTags();
    QString concert() const;
    QList<QVariantMap> m_undo, m_redo;           // {all, defs}
    QString m_root, m_folder, m_track, m_report;
    QVariantMap m_all, m_defs;
    bool m_dirty = false;
    QProcess *m_proc = nullptr;
};
