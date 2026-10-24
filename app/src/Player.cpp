// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "Player.h"

#include "AppLog.h"
#include "AudioFile.h"

#include <QAudioDevice>
#include <QAudioSink>
#include <QMediaDevices>
#include <QTimer>
#include <cmath>
#include <cstring>
#include <thread>

namespace {
// pull-mode source for QAudioSink: asks the player for stereo float frames
class Source : public QIODevice {
public:
    explicit Source(Player *p) : m_p(p) { open(QIODevice::ReadOnly); }
    qint64 readData(char *data, qint64 maxlen) override
    {
        const qint64 frames = maxlen / qint64(2 * sizeof(float));
        m_p->render(reinterpret_cast<float *>(data), frames);
        return frames * qint64(2 * sizeof(float));
    }
    qint64 writeData(const char *, qint64) override { return -1; }
    qint64 bytesAvailable() const override { return 1 << 20; }
    bool isSequential() const override { return true; }

private:
    Player *m_p;
};
constexpr int kFade = 288;   // 6 ms at 48 kHz
}

Player::Player(QObject *parent) : QObject(parent)
{
    m_audioCtx = new QObject;
    m_audioCtx->moveToThread(&m_audioThread);
    m_audioThread.setObjectName(QStringLiteral("audio"));
    m_audioThread.start(QThread::HighestPriority);
    auto *t = new QTimer(this);   // position for the screen
    t->setInterval(40);
    connect(t, &QTimer::timeout, this, [this] { if (m_playing) emit positionChanged(); });
    t->start();
}

Player::~Player()
{
    stop();
    m_audioThread.quit();
    m_audioThread.wait();
    delete m_audioCtx;
}

void Player::preload(const QStringList &paths)
{
    std::thread([paths] {
        for (const QString &p : paths)
            AudioCache::instance().get(p);
    }).detach();
}

bool Player::load(const QStringList &paths, bool keep)
{
    const bool was = m_playing;
    const double pos = position(), l0 = loopStart(), l1 = loopEnd();
    // another track of the same song while playing: swap inside the running stream (crossfade),
    // no restart of the audio output
    bool live = keep && m_playing;
    if (!live)
        stop();
    std::vector<ClipPtr> bufs;
    int rate = 0;
    m_error.clear();
    for (const QString &p : paths) {
        ClipPtr a = AudioCache::instance().get(p);
        if (!a->error.isEmpty()) {
            m_error = a->error;
            break;
        }
        if (rate && a->rate != rate) {
            m_error = QStringLiteral("%1: sample rate %2, the others %3").arg(p).arg(a->rate).arg(rate);
            break;
        }
        rate = a->rate;
        bufs.push_back(a);
    }
    if (live && (bufs.empty() || !m_error.isEmpty() || bufs[0]->rate != m_rate)) {
        stop();
        live = false;
    }
    if (!m_error.isEmpty()) {
        qWarning("load: %s", qPrintable(m_error));
        emit loadedChanged();
        return false;
    }
    size_t len = bufs.empty() ? 0 : bufs[0]->x.size();
    for (auto &b : bufs)
        len = std::min(len, b->x.size());
    {
        QMutexLocker l(&m_lock);
        if (live) {
            m_old = m_buf;
            m_oldSel = m_sel;
            m_oldRem = m_removed;
            m_swap = qMax(1, kFade * m_rate / 48000);
        }
        m_buf = std::move(bufs);
        m_sources = paths;
        const bool same = keep && rate == m_rate;
        m_rate = rate;
        m_len = qint64(len);
        m_l0 = same ? qBound<qint64>(0, qint64(l0 * rate), m_len) : 0;
        m_l1 = same ? qBound<qint64>(m_l0 + 1, qint64(l1 * rate), m_len) : m_len;
        m_pos = same ? qBound<qint64>(0, qint64(pos * rate), m_len - 1) : 0;
        m_sel = qBound(0, m_sel.load(), int(m_buf.size()) - 1);
        if (m_buf.size() > 1 && m_sel == 0)
            m_sel = 1;
    }
    logInfo(QStringLiteral("player: %1 files, %2 Hz, %3 s").arg(m_buf.size()).arg(m_rate).arg(duration(), 0, 'f', 1));
    emit loadedChanged();
    emit loopChanged();
    emit positionChanged();
    if (keep && was && !live)
        play();
    return true;
}

float Player::sampleOf(int idx, bool rem, qint64 p) const
{
    const float v = m_buf[size_t(idx)]->x[size_t(p)];
    if (rem && idx > 0)
        return (m_buf[0]->x[size_t(p)] - v) * m_gainRem.load();
    return v;
}

void Player::render(float *out, qint64 frames)
{
    QMutexLocker l(&m_lock);
    if (m_buf.empty() || !m_playing) {
        std::memset(out, 0, size_t(frames) * 2 * sizeof(float));
        return;
    }
    const int sel = m_sel.load();
    const bool rem = m_removed.load();
    if (sel != m_prevSel || rem != m_prevRem)
        m_fade = kFade * m_rate / 48000;
    const int fadeLen = qMax(1, kFade * m_rate / 48000);
    qint64 p = m_pos.load();
    float peak = 0;
    const bool loop = m_loopOn.load();
    for (qint64 i = 0; i < frames; ++i) {
        if (p >= m_len - 1) {   // end of the file: from the start (of the loop when it is on)
            p = loop ? m_l0 : 0;
            m_frac = 0;
        }
        // linear interpolation between p and p+1 when the output runs at another rate
        auto at = [&](int idx, bool r) {
            const float a = sampleOf(idx, r, p);
            return m_step == 1.0 ? a : a + float(m_frac) * (sampleOf(idx, r, p + 1) - a);
        };
        float v = at(sel, rem);
        if (m_swap > 0) {   // crossfade from the files before a live load
            const float w = float(m_swap) / float(fadeLen);
            const auto &o = m_old[size_t(qMin(m_oldSel, int(m_old.size()) - 1))]->x;
            float ov = p < qint64(o.size()) ? o[size_t(p)] : 0.0f;
            if (m_oldRem && m_oldSel > 0 && p < qint64(m_old[0]->x.size()))
                ov = (m_old[0]->x[size_t(p)] - ov) * m_gainRem.load();
            v = w * ov + (1 - w) * v;
            if (--m_swap == 0)
                m_old.clear();
        }
        if (m_fade > 0) {   // crossfade from what played before the switch
            const float w = float(m_fade) / float(fadeLen);
            v = w * at(m_prevSel, m_prevRem) + (1 - w) * v;
            if (--m_fade == 0) {
                m_prevSel = sel;
                m_prevRem = rem;
            }
        }
        out[2 * i] = out[2 * i + 1] = v;
        peak = std::max(peak, std::fabs(v));
        m_frac += m_step;
        const qint64 whole = qint64(m_frac);
        const qint64 before = p;
        p += whole;
        m_frac -= double(whole);
        if (loop && before < m_l1 - 1 && p >= m_l1 - 1)   // reached the loop end: back to its start
            p = m_l0 + (p - (m_l1 - 1));
    }
    if (m_fade == 0) {
        m_prevSel = sel;
        m_prevRem = rem;
    }
    m_pos = p;
    m_meter = peak > 0 ? 20.0 * std::log10(double(peak)) : -120.0;
}

QString Player::audioInfo()
{
    const QAudioDevice dev = QMediaDevices::defaultAudioOutput();
    if (dev.isNull())
        return QStringLiteral("no audio output");
    QStringList rates;
    for (int r : {44100, 48000, 88200, 96000, 192000}) {
        QAudioFormat f;
        f.setSampleRate(r);
        f.setChannelCount(2);
        f.setSampleFormat(QAudioFormat::Float);
        if (dev.isFormatSupported(f))
            rates << QString::number(r);
    }
    return QStringLiteral("%1; preferred %2 Hz; float stereo at: %3").arg(dev.description())
        .arg(dev.preferredFormat().sampleRate()).arg(rates.isEmpty() ? QStringLiteral("none") : rates.join(QStringLiteral(", ")));
}

void Player::renderForTest(int frames)
{
    std::vector<float> b(size_t(frames) * 2);
    m_step = 1.0;
    const bool was = m_playing;
    m_playing = true;
    render(b.data(), frames);
    m_playing = was;
}

void Player::play()
{
    if (m_buf.empty() || m_playing)
        return;
    QAudioFormat f;
    f.setSampleRate(m_rate);
    f.setChannelCount(2);
    f.setSampleFormat(QAudioFormat::Float);
    const QAudioDevice dev = QMediaDevices::defaultAudioOutput();
    if (dev.isNull()) {
        m_error = QStringLiteral("no audio output");
        qWarning("play: %s", qPrintable(m_error));
        emit loadedChanged();
        return;
    }
    if (!dev.isFormatSupported(f)) {   // e.g. a 96 kHz file on a 48 kHz output: resample while playing
        f.setSampleRate(dev.preferredFormat().sampleRate());
        if (!dev.isFormatSupported(f)) {
            m_error = QStringLiteral("the audio output takes neither %1 Hz nor %2 Hz float").arg(m_rate).arg(f.sampleRate());
            qWarning("play: %s", qPrintable(m_error));
            emit loadedChanged();
            return;
        }
    }
    m_outRate = f.sampleRate();
    m_step = double(m_rate) / double(m_outRate);
    m_frac = 0;
    m_outputInfo = QStringLiteral("%1 at %2 Hz%3").arg(dev.description()).arg(m_outRate)
                       .arg(m_outRate != m_rate ? QStringLiteral(" (file %1 Hz, resampled)").arg(m_rate) : QString());
    logInfo(QStringLiteral("play: %1").arg(m_outputInfo));
    m_playing = true;
    m_prevSel = m_sel;
    m_prevRem = m_removed;
    const double vol = m_muted ? 0.0 : 1.0;
    QMetaObject::invokeMethod(m_audioCtx, [this, dev, f, vol] {
        m_sink = new QAudioSink(dev, f);   // created in the audio thread: it pulls there
        m_sink->setBufferSize(m_outRate / 10 * 2 * int(sizeof(float)));   // ~100 ms: switching feels instant
        m_dev = std::make_unique<Source>(this);
        m_sink->setVolume(vol);
        m_sink->start(m_dev.get());
    }, Qt::BlockingQueuedConnection);
    emit playingChanged();
}

void Player::stop()
{
    if (!m_playing)
        return;
    m_playing = false;
    QMetaObject::invokeMethod(m_audioCtx, [this] {
        if (m_sink) {
            m_sink->stop();
            delete m_sink;
            m_sink = nullptr;
        }
        m_dev.reset();
    }, Qt::BlockingQueuedConnection);
    emit playingChanged();
    emit positionChanged();
}

void Player::setMuted(bool m)
{
    m_muted = m;
    QMetaObject::invokeMethod(m_audioCtx, [this, m] {
        if (m_sink)
            m_sink->setVolume(m ? 0.0 : 1.0);
    });
    emit playingChanged();
}

void Player::seek(double s)
{
    m_pos = qBound<qint64>(0, qint64(s * m_rate), qMax<qint64>(0, m_len - 2));
    m_frac = 0;
    emit positionChanged();
}

void Player::setLoopOn(bool on)
{
    if (on == m_loopOn)
        return;
    m_loopOn = on;
    emit loopChanged();
}

void Player::select(int i)
{
    if (i < 0 || i >= count() || i == m_sel)
        return;
    m_sel = i;
    emit selectedChanged();
}

void Player::setRemoved(bool r)
{
    if (r == m_removed)
        return;
    m_removed = r;
    emit selectedChanged();
}

void Player::setBoostDb(double d)
{
    m_boost = d;
    m_gainRem = float(std::pow(10.0, d / 20.0));
    emit selectedChanged();
}

void Player::setLoop(double a, double b, bool jump)
{
    if (b < a)
        std::swap(a, b);
    {
        QMutexLocker l(&m_lock);
        m_l0 = qBound<qint64>(0, qint64(a * m_rate), m_len);
        m_l1 = qBound<qint64>(m_l0 + 1, qint64(b * m_rate), qMax<qint64>(m_len, 1));
        if (jump && (m_pos < m_l0 || m_pos >= m_l1))
            m_pos = m_l0;
    }
    emit loopChanged();
    emit positionChanged();
}

double Player::differenceDb(int i) const
{
    if (i <= 0 || i >= count())
        return 0;
    double eo = 0, ed = 0;
    for (qint64 p = m_l0; p < m_l1; p += 2) {
        const double o = m_buf[0]->x[size_t(p)], d = o - m_buf[size_t(i)]->x[size_t(p)];
        eo += o * o;
        ed += d * d;
    }
    if (ed <= 0)
        return -120;
    return 10.0 * std::log10(ed / std::max(eo, 1e-30));
}
