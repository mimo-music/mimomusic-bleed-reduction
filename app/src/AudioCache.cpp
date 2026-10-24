// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "AudioCache.h"

#include "AppLog.h"
#include "AudioFile.h"

#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <algorithm>
#include <cmath>

constexpr int Clip::kBlock[Clip::kLevels];

void Clip::range(qint64 a, qint64 b, float &lo, float &hi) const
{
    const qint64 n = qint64(x.size());
    a = std::max<qint64>(0, a);
    b = std::min(n, b);
    lo = hi = 0;
    if (b <= a)
        return;
    lo = hi = x[size_t(a)];
    // the biggest level whose blocks fit at least twice: edges from the level below / the samples
    for (int k = kLevels - 1; k >= 0; --k) {
        const qint64 B = kBlock[k];
        const qint64 b0 = (a + B - 1) / B, b1 = b / B;   // whole blocks inside [a, b)
        if (b1 - b0 < 2)
            continue;
        for (qint64 i = b0; i < b1; ++i) {
            lo = std::min(lo, mn[k][size_t(i)]);
            hi = std::max(hi, mx[k][size_t(i)]);
        }
        float l2, h2;
        range(a, b0 * B, l2, h2);
        if (b0 * B > a) { lo = std::min(lo, l2); hi = std::max(hi, h2); }
        range(b1 * B, b, l2, h2);
        if (b > b1 * B) { lo = std::min(lo, l2); hi = std::max(hi, h2); }
        return;
    }
    for (qint64 i = a; i < b; ++i) {
        const float v = x[size_t(i)];
        lo = std::min(lo, v);
        hi = std::max(hi, v);
    }
}

void Clip::bandPeaks(qint64 a, qint64 b, float *out) const
{
    out[0] = out[1] = out[2] = 0;
    // the coarsest level with at least one block inside, else the finest
    int k = kLevels - 1;
    while (k > 0 && (b - a) / kBlock[k] < 1)
        --k;
    const qint64 B = kBlock[k], nb = qint64(bands[k].size() / 3);
    const qint64 b0 = std::max<qint64>(0, a / B), b1 = std::min(nb, std::max(b0 + 1, (b + B - 1) / B));
    for (qint64 i = b0; i < b1; ++i)
        for (int j = 0; j < 3; ++j)
            out[j] = std::max(out[j], bands[k][size_t(3 * i + j)]);
}

AudioCache &AudioCache::instance()
{
    static AudioCache c;
    return c;
}

static qint64 memTotal()
{
    QFile f(QStringLiteral("/proc/meminfo"));
    if (f.open(QIODevice::ReadOnly)) {
        const QByteArray l = f.readLine();   // MemTotal:  16000000 kB
        const QList<QByteArray> p = l.simplified().split(' ');
        if (p.size() >= 2)
            return p[1].toLongLong() * 1024;
    }
    return qint64(8) << 30;
}

void AudioCache::build(Clip &cl)
{
    Clip *c = &cl;
    for (float v : c->x)
        c->peak = std::max(c->peak, std::fabs(v));
    // pyramid: level 0 from the samples, each next level from the one below
    for (int k = 0; k < Clip::kLevels; ++k) {
        const size_t B = size_t(Clip::kBlock[k]), nb = c->x.size() / B;
        c->mn[k].resize(nb);
        c->mx[k].resize(nb);
        const size_t f = k ? B / size_t(Clip::kBlock[k - 1]) : B;
        for (size_t i = 0; i < nb; ++i) {
            float lo, hi;
            if (k == 0) {
                lo = hi = c->x[i * B];
                for (size_t j = 1; j < B; ++j) {
                    lo = std::min(lo, c->x[i * B + j]);
                    hi = std::max(hi, c->x[i * B + j]);
                }
            } else {
                lo = c->mn[k - 1][i * f];
                hi = c->mx[k - 1][i * f];
                for (size_t j = 1; j < f; ++j) {
                    lo = std::min(lo, c->mn[k - 1][i * f + j]);
                    hi = std::max(hi, c->mx[k - 1][i * f + j]);
                }
            }
            c->mn[k][i] = lo;
            c->mx[k][i] = hi;
        }
    }
    // band peaks: 2nd-order low pass 250 Hz and high pass 2.5 kHz (RBJ biquads), mid = the rest
    if (c->rate > 0 && !c->x.empty()) {
        struct Bq { double b0, b1, b2, a1, a2, z1 = 0, z2 = 0;
            float run(float x) { const double y = b0 * x + z1; z1 = b1 * x - a1 * y + z2; z2 = b2 * x - a2 * y; return float(y); } };
        auto make = [&](double fc, bool high) {
            const double w = 2 * M_PI * fc / c->rate, cs = std::cos(w), al = std::sin(w) / (2 * 0.7071), a0 = 1 + al;
            Bq q;
            q.b0 = (high ? (1 + cs) / 2 : (1 - cs) / 2) / a0;
            q.b1 = (high ? -(1 + cs) : (1 - cs)) / a0;
            q.b2 = q.b0;
            q.a1 = -2 * cs / a0;
            q.a2 = (1 - al) / a0;
            return q;
        };
        Bq lp = make(250, false), hp = make(2500, true);
        const size_t B0 = size_t(Clip::kBlock[0]), nb0 = c->x.size() / B0;
        c->bands[0].assign(3 * nb0, 0.0f);
        for (size_t i = 0; i < nb0 * B0; ++i) {
            const float x = c->x[i], l = lp.run(x), h = hp.run(x), m = x - l - h;
            float *o = &c->bands[0][3 * (i / B0)];
            o[0] = std::max(o[0], std::fabs(l));
            o[1] = std::max(o[1], std::fabs(m));
            o[2] = std::max(o[2], std::fabs(h));
        }
        for (int k = 1; k < Clip::kLevels; ++k) {
            const size_t f = size_t(Clip::kBlock[k] / Clip::kBlock[k - 1]), nb = c->bands[k - 1].size() / 3 / f;
            c->bands[k].assign(3 * nb, 0.0f);
            for (size_t i = 0; i < nb; ++i)
                for (size_t j = 0; j < f; ++j)
                    for (int q = 0; q < 3; ++q)
                        c->bands[k][3 * i + q] = std::max(c->bands[k][3 * i + q], c->bands[k - 1][3 * (i * f + j) + q]);
        }
    }
}

ClipPtr AudioCache::get(const QString &path)
{
    // "range:<path>|<from s>|<to s>": a part of a file (the product: the original over the rendered range)
    if (path.startsWith(QLatin1String("range:"))) {
        const QStringList p = path.mid(6).split(QLatin1Char('|'));
        if (p.size() != 3)
            return std::make_shared<Clip>();
        const ClipPtr A = get(p[0]);
        {
            QMutexLocker l(&m_lock);
            auto it = m_map.find(path);
            if (it != m_map.end() && it->deps.size() == 1 && it->deps[0] == A) {
                it->used = ++m_tick;
                return it->clip;
            }
        }
        auto c = std::make_shared<Clip>();
        c->path = path;
        c->rate = A->rate;
        c->error = A->error;
        if (c->error.isEmpty()) {
            const size_t n = A->x.size();
            const size_t a0 = std::min(n, size_t(std::max(0.0, p[1].toDouble()) * A->rate));
            const double to = p[2].toDouble();
            const size_t b0 = to > 0 ? std::min(n, size_t(to * A->rate)) : n;
            c->x.assign(A->x.begin() + qint64(a0), A->x.begin() + qint64(std::max(a0, b0)));
        }
        build(*c);
        QMutexLocker l(&m_lock);
        m_map[path] = Entry{c, 1, ++m_tick, {A}};
        trim();
        return c;
    }
    // derived clips: "diff:a|b" = a - b (what a version removed); "mix:a|b|w" = (1 - w) a + w b
    // (catx strength: catx = per-frequency gain on cat, so the blend is a milder gain, exactly)
    const bool isDiff = path.startsWith(QLatin1String("diff:")), isMix = path.startsWith(QLatin1String("mix:"));
    if (isDiff || isMix) {
        QStringList ab = path.mid(isDiff ? 5 : 4).split(QLatin1Char('|'));
        double w = 0;
        if (isMix) {
            bool ok = false;
            w = ab.size() == 3 ? ab.takeLast().toDouble(&ok) : 0;
            if (!ok)
                return std::make_shared<Clip>();
        }
        if (ab.size() != 2)
            return std::make_shared<Clip>();
        const ClipPtr A = get(ab[0]), B = get(ab[1]);
        const qint64 mtime = qMax(A ? 1 : 0, 1);   // derived: rebuilt when either input was re-read
        {
            QMutexLocker l(&m_lock);
            auto it = m_map.find(path);
            if (it != m_map.end() && it->deps.size() == 2 && it->deps[0] == A && it->deps[1] == B) {
                it->used = ++m_tick;
                return it->clip;
            }
        }
        auto c = std::make_shared<Clip>();
        c->path = path;
        c->rate = A->rate;
        c->error = !A->error.isEmpty() ? A->error : B->error;
        if (c->error.isEmpty() && A->rate != B->rate)
            c->error = QStringLiteral("different sample rates");
        if (c->error.isEmpty()) {
            const size_t n = std::min(A->x.size(), B->x.size());
            c->x.resize(n);
            if (isDiff)
                for (size_t i = 0; i < n; ++i)
                    c->x[i] = A->x[i] - B->x[i];
            else
                for (size_t i = 0; i < n; ++i)
                    c->x[i] = float((1 - w) * A->x[i] + w * B->x[i]);
        }
        build(*c);
        QMutexLocker l(&m_lock);
        m_map[path] = Entry{c, mtime, ++m_tick, {A, B}};
        trim();
        return c;
    }
    const qint64 mtime = QFileInfo(path).lastModified().toMSecsSinceEpoch();
    {
        QMutexLocker l(&m_lock);
        auto it = m_map.find(path);
        if (it != m_map.end() && it->mtime == mtime) {
            it->used = ++m_tick;
            return it->clip;
        }
    }
    QElapsedTimer t;
    t.start();
    auto c = std::make_shared<Clip>();
    c->path = path;
    Audio a = readMono(path);
    c->error = a.error;
    c->rate = a.rate;
    c->x = std::move(a.data);
    build(*c);
    if (c->error.isEmpty())
        logInfo(QStringLiteral("audio: read %1 (%2 s, %3 Hz) in %4 ms").arg(QFileInfo(path).fileName())
                    .arg(c->duration(), 0, 'f', 1).arg(c->rate).arg(t.elapsed()));
    QMutexLocker l(&m_lock);
    m_map[path] = Entry{c, mtime, ++m_tick, {}};
    trim();
    return c;
}

qint64 AudioCache::bytes() const
{
    QMutexLocker l(&m_lock);
    qint64 b = 0;
    for (const Entry &e : m_map)
        b += qint64(e.clip->x.size()) * qint64(sizeof(float)) * 9 / 8;
    return b;
}

void AudioCache::trim()
{
    if (!m_budget)
        m_budget = std::min<qint64>(qint64(3) << 30, memTotal() / 4);
    auto size = [this] {
        qint64 b = 0;
        for (const Entry &e : m_map)
            b += qint64(e.clip->x.size()) * qint64(sizeof(float)) * 9 / 8;
        return b;
    };
    while (size() > m_budget) {
        // the least recently used file nobody holds
        auto victim = m_map.end();
        for (auto it = m_map.begin(); it != m_map.end(); ++it)
            if (it->clip.use_count() == 1 && (victim == m_map.end() || it->used < victim->used))
                victim = it;
        if (victim == m_map.end())
            return;
        m_map.erase(victim);
    }
}
