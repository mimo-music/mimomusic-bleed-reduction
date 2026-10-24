// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// Plays one sample: the original and its versions, all loaded and running in
// sync; switching only changes which one is heard (6 ms crossfade, no click,
// position kept). "Removed" plays original minus version (+ boost). Loop range
// like a DJ player: when on, playback wraps at its end once it got there from
// inside or before it; playing after it goes on to the end of the file.
#include "AudioCache.h"

#include <QAudioFormat>
#include <QIODevice>
#include <QMutex>
#include <QObject>
#include <QStringList>
#include <QThread>
#include <QVariantList>
#include <atomic>
#include <memory>
#include <vector>

class QAudioSink;

class Player : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool loaded READ loaded NOTIFY loadedChanged)
    Q_PROPERTY(int count READ count NOTIFY loadedChanged)
    Q_PROPERTY(int rate READ rate NOTIFY loadedChanged)
    Q_PROPERTY(double duration READ duration NOTIFY loadedChanged)
    Q_PROPERTY(double position READ position WRITE seek NOTIFY positionChanged)
    Q_PROPERTY(bool playing READ playing NOTIFY playingChanged)
    Q_PROPERTY(int selected READ selected WRITE select NOTIFY selectedChanged)
    Q_PROPERTY(bool removed READ removed WRITE setRemoved NOTIFY selectedChanged)
    Q_PROPERTY(double boostDb READ boostDb WRITE setBoostDb NOTIFY selectedChanged)
    Q_PROPERTY(double loopStart READ loopStart NOTIFY loopChanged)
    Q_PROPERTY(double loopEnd READ loopEnd NOTIFY loopChanged)
    Q_PROPERTY(bool loopOn READ loopOn WRITE setLoopOn NOTIFY loopChanged)
    Q_PROPERTY(QStringList sources READ sources NOTIFY loadedChanged)
    Q_PROPERTY(QString error READ error NOTIFY loadedChanged)
    Q_PROPERTY(QString outputInfo READ outputInfo NOTIFY playingChanged)
    Q_PROPERTY(bool muted READ muted WRITE setMuted NOTIFY playingChanged)
public:
    explicit Player(QObject *parent = nullptr);
    ~Player() override;

    // paths: the original first, then the versions; false on error (see error).
    // keep: stay at the same position and loop (switching to another track of the song)
    Q_INVOKABLE bool load(const QStringList &paths, bool keep = false);
    Q_INVOKABLE void play();
    Q_INVOKABLE void stop();
    Q_INVOKABLE void toggle() { m_playing ? stop() : play(); }
    // read these files into the cache in the background (the lanes of a song: switching is instant)
    Q_INVOKABLE void preload(const QStringList &paths);
    // jump: playback goes to the loop start if it is outside (false while dragging an edge)
    Q_INVOKABLE void setLoop(double a, double b, bool jump = true);
    Q_INVOKABLE void wholeSample() { setLoop(0, duration()); }
    // level of (original - version i) in the loop, relative to the original, dB
    Q_INVOKABLE double differenceDb(int i) const;
    // the last block's peak level of what is heard, dB (meter)
    Q_INVOKABLE double meterDb() const { return m_meter.load(); }

    bool loaded() const { return !m_buf.empty(); }
    int count() const { return int(m_buf.size()); }
    bool loopOn() const { return m_loopOn.load(); }
    void setLoopOn(bool on);
    QStringList sources() const { return m_sources; }
    int rate() const { return m_rate; }
    double duration() const { return m_len ? double(m_len) / m_rate : 0.0; }
    double position() const { return double(m_pos.load()) / qMax(1, m_rate); }
    Q_INVOKABLE void seek(double s);
    bool playing() const { return m_playing; }
    int selected() const { return m_sel.load(); }
    void select(int i);
    bool removed() const { return m_removed.load(); }
    void setRemoved(bool r);
    double boostDb() const { return m_boost; }
    void setBoostDb(double d);
    double loopStart() const { return double(m_l0) / qMax(1, m_rate); }
    double loopEnd() const { return double(m_l1) / qMax(1, m_rate); }
    QString error() const { return m_error; }
    QString outputInfo() const { return m_outputInfo; }
    bool muted() const { return m_muted; }
    void setMuted(bool m);
    // the default output and the sample rates it takes (Debug view, --audio-info)
    Q_INVOKABLE static QString audioInfo();

    // the audio thread's side: n stereo frames into out
    void render(float *out, qint64 frames);
    // for tests without a sound card: render and advance like the card would
    Q_INVOKABLE void renderForTest(int frames);

signals:
    void loadedChanged();
    void positionChanged();
    void playingChanged();
    void selectedChanged();
    void loopChanged();

private:
    float sampleOf(int idx, bool rem, qint64 p) const;

    std::vector<ClipPtr> m_buf;    // [0] original
    std::vector<ClipPtr> m_old;    // what played before a load(keep) while playing: crossfaded out
    int m_oldSel = 0, m_swap = 0;
    bool m_oldRem = false;
    QStringList m_sources;
    std::atomic<bool> m_loopOn{true};
    int m_rate = 0;
    qint64 m_len = 0;
    std::atomic<qint64> m_pos{0};
    double m_step = 1.0;           // file samples per output sample (1 unless the output runs at another rate)
    double m_frac = 0.0;           // fractional file position when resampling
    int m_outRate = 0;
    bool m_muted = false;
    QString m_outputInfo;
    std::atomic<int> m_sel{1};
    std::atomic<bool> m_removed{false};
    std::atomic<float> m_gainRem{2.0f};
    std::atomic<double> m_meter{-120.0};
    qint64 m_l0 = 0, m_l1 = 0;
    double m_boost = 6.0;
    int m_prevSel = 1;
    bool m_prevRem = false;
    int m_fade = 0;                // samples of crossfade left
    std::atomic<bool> m_playing{false};
    // the audio output lives in its own thread: a busy screen (painting, reading files) can't starve it
    QThread m_audioThread;
    QObject *m_audioCtx = nullptr;
    QString m_error;
    QAudioSink *m_sink = nullptr;
    std::unique_ptr<QIODevice> m_dev;
    QMutex m_lock;                 // m_buf/m_len/loop while the audio thread reads
};
