// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// Audio files in memory, shared by the player and the waveform views (each
// file is read once): mono samples plus a min/max pyramid for drawing at any
// zoom. Files no view or player holds any more are dropped when the cache
// grows past its budget (a quarter of the memory, at most 3 GB).
#include <QHash>
#include <QMutex>
#include <QString>
#include <memory>
#include <vector>

struct Clip {
    QString path, error;
    std::vector<float> x;              // mono
    int rate = 0;
    float peak = 0;                    // largest |sample|
    // pyramid: level k has min/max pairs over blocks of kBlock[k] samples
    static constexpr int kLevels = 4;
    static constexpr int kBlock[kLevels] = {32, 256, 2048, 16384};
    std::vector<float> mn[kLevels], mx[kLevels];
    // per block, the peak of three bands (low < 250 Hz, mid, high > 2.5 kHz), interleaved: Mixxx-like colours
    std::vector<float> bands[kLevels];
    double duration() const { return rate ? double(x.size()) / rate : 0.0; }
    // min/max of the samples [a, b) using the pyramid where it can
    void range(qint64 a, qint64 b, float &lo, float &hi) const;
    // the band peaks over [a, b) (block resolution); out[3]
    void bandPeaks(qint64 a, qint64 b, float *out) const;
};
using ClipPtr = std::shared_ptr<const Clip>;

class AudioCache {
public:
    static AudioCache &instance();
    // the file (read on first use, again when it changed on disk); check ->error.
    // "diff:<a>|<b>" is a minus b (what a version removed from the original); "mix:<a>|<b>|<w>" is (1 - w) a + w b;
    // "range:<path>|<from s>|<to s>" a part of a file (to 0: the end)
    ClipPtr get(const QString &path);
    qint64 bytes() const;

private:
    static void build(Clip &c);      // peak, pyramid, band peaks
    struct Entry { ClipPtr clip; qint64 mtime = 0, used = 0; std::vector<ClipPtr> deps; };
    void trim();
    mutable QMutex m_lock;
    QHash<QString, Entry> m_map;
    qint64 m_tick = 0, m_budget = 0;
};
