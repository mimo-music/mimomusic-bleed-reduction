// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "WaveView.h"

#include <QPainter>
#include <cmath>

WaveView::WaveView(QQuickItem *parent) : QQuickPaintedItem(parent)
{
    setAntialiasing(false);
    connect(this, &WaveView::repaintNeeded, this, [this] { update(); });
    connect(this, &WaveView::sourceChanged, this, [this] { update(); });
}

void WaveView::setSource(const QString &s)
{
    // the same name can be a new file (a render rewrites render/<track>.wav): the cache knows
    ClipPtr c = s.isEmpty() ? nullptr : AudioCache::instance().get(s);
    if (s == m_source && c == m_clip)
        return;
    m_source = s;
    m_clip = c;
    if (m_clip && !m_clip->error.isEmpty())
        qWarning("wave: %s", qPrintable(m_clip->error));
    emit sourceChanged();
}

void WaveView::setRevision(int r)
{
    if (r == m_rev)
        return;
    m_rev = r;
    ClipPtr c = m_source.isEmpty() ? nullptr : AudioCache::instance().get(m_source);
    if (c != m_clip) {
        m_clip = c;
        emit sourceChanged();
    }
}

double WaveView::peakDb() const
{
    return m_clip && m_clip->peak > 0 ? 20.0 * std::log10(double(m_clip->peak)) : -120.0;
}

QColor WaveView::tagColor(int i)
{
    // the plugins' palette, readable on the dark background (no yellow: that is the loop)
    static const QColor c[] = {{90, 155, 225}, {85, 175, 110}, {230, 125, 70}, {180, 130, 220},
                               {210, 100, 155}, {70, 180, 180}, {180, 140, 100}, {160, 200, 80}};
    return i < 0 ? QColor(140, 144, 152) : c[i % 8];
}

double WaveView::y(float v, double mid) const
{
    // v already normalized: -1..1 -> -mid..mid
    double a = std::fabs(double(v));
    if (m_db)
        a = a > 0 ? std::max(0.0, 1.0 + 20.0 * std::log10(a) / m_dbRange) : 0.0;
    a = std::min(a, 1.0);
    return (v < 0 ? -a : a) * mid * 0.96;
}

void WaveView::paint(QPainter *p)
{
    const double w = width(), h = height(), mid = h / 2;
    p->fillRect(QRectF(0, 0, w, h), m_back);
    if (m_v1 <= m_v0 || w < 2)
        return;
    const double spx = (m_v1 - m_v0) / w;   // seconds per pixel
    auto xOf = [&](double t) { return (t - m_v0) / spx; };
    // passages: a tint of their colour behind the wave
    if (m_tint > 0)
        for (const QVariant &v : m_passages) {
            const QVariantMap m = v.toMap();
            const double x0 = xOf(m.value(QStringLiteral("start")).toDouble());
            const double x1 = xOf(m.value(QStringLiteral("end")).toDouble());
            if (x1 < 0 || x0 > w)
                continue;
            QColor c = tagColor(int(m_kinds.indexOf(m.value(QStringLiteral("kind")).toString())));
            c.setAlphaF(float(m_tint));
            p->fillRect(QRectF(x0, 0, x1 - x0, h), c);
        }
    p->setPen(QPen(m_line, 1));
    p->drawLine(QPointF(0, mid), QPointF(w, mid));
    if (m_db) {   // -6 dB steps as faint lines
        QColor g = m_line;
        g.setAlpha(110);
        p->setPen(QPen(g, 1, Qt::DotLine));
        for (double d = -12; d > -m_dbRange; d -= 12) {
            const double yy = (1.0 + d / m_dbRange) * mid * 0.96;
            p->drawLine(QPointF(0, mid - yy), QPointF(w, mid - yy));
            p->drawLine(QPointF(0, mid + yy), QPointF(w, mid + yy));
        }
    }
    if (!m_clip || m_clip->x.empty())
        return;
    const Clip &c = *m_clip;
    const float g = m_norm && c.peak > 0 ? 1.0f / c.peak : 1.0f;
    const double spp = spx * c.rate;        // samples per pixel
    p->setPen(QPen(m_color, 1));
    if (spp >= 1.0) {
        QVector<QLineF> lines;
        lines.reserve(int(w) + 1);
        // spectral: low red, mid green, high blue, scaled to the strongest (Mixxx's RGB waveform);
        // dimmed like the plain colour when this lane isn't the one you hear
        const double dimF = m_color.valueF() < 0.7 ? 0.55 : 1.0;
        for (int x = 0; x < int(std::ceil(w)); ++x) {
            const qint64 a = qint64(std::floor((m_v0 + x * spx) * c.rate));
            const qint64 b = std::max(a + 1, qint64(std::floor((m_v0 + (x + 1) * spx) * c.rate)));
            if (b <= 0 || a >= qint64(c.x.size()))
                continue;
            float lo, hi;
            c.range(a, b, lo, hi);
            const double y0 = mid - y(hi * g, mid), y1 = mid - y(lo * g, mid);
            if (m_spectral) {
                float bp[3];
                c.bandPeaks(a, b, bp);
                // weights: highs carry less energy; boost them so cymbals and consonants show
                const double r = bp[0], gg = bp[1] * 1.2, bl = bp[2] * 2.2, m = std::max({r, gg, bl, 1e-9});
                QColor col = QColor::fromRgbF(float(std::min(1.0, 0.25 + 0.75 * r / m) * dimF),
                                              float(std::min(1.0, 0.25 + 0.75 * gg / m) * dimF),
                                              float(std::min(1.0, 0.25 + 0.75 * bl / m) * dimF));
                p->setPen(QPen(col, 1));
                p->drawLine(QLineF(x + 0.5, y0, x + 0.5, std::max(y1, y0 + 1)));
            } else {
                lines << QLineF(x + 0.5, y0, x + 0.5, std::max(y1, y0 + 1));
            }
        }
        if (!lines.isEmpty())
            p->drawLines(lines);
    } else {
        // zoomed in past one sample per pixel: the samples, joined
        p->setRenderHint(QPainter::Antialiasing, true);
        QPolygonF poly;
        const qint64 a = std::max<qint64>(0, qint64(std::floor(m_v0 * c.rate)) - 1);
        const qint64 b = std::min<qint64>(qint64(c.x.size()), qint64(std::ceil(m_v1 * c.rate)) + 2);
        for (qint64 i = a; i < b; ++i)
            poly << QPointF(xOf(double(i) / c.rate), mid - y(c.x[size_t(i)] * g, mid));
        p->drawPolyline(poly);
        if (spp < 0.12)
            for (const QPointF &pt : poly)
                p->drawEllipse(pt, 1.6, 1.6);
    }
}

// ---------------------------------------------------------------- ruler

TimeRuler::TimeRuler(QQuickItem *parent) : QQuickPaintedItem(parent)
{
    connect(this, &TimeRuler::repaintNeeded, this, [this] { update(); });
}

QString TimeRuler::format(double t, int decimals)
{
    const bool neg = t < 0;
    t = std::fabs(t);
    const int m = int(t / 60);
    const double s = t - 60 * m;
    return QStringLiteral("%1%2:%3").arg(neg ? QStringLiteral("-") : QString()).arg(m)
        .arg(s, decimals ? 3 + decimals : 2, 'f', decimals, QLatin1Char('0'));
}

void TimeRuler::paint(QPainter *p)
{
    const double w = width(), h = height();
    p->fillRect(QRectF(0, 0, w, h), m_back);
    if (m_v1 <= m_v0)
        return;
    const double spx = (m_v1 - m_v0) / w;
    // the smallest step with labels at least 70 px apart
    static const double steps[] = {0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300};
    double step = 600;
    for (double s : steps)
        if (s / spx >= 70) { step = s; break; }
    const int dec = step >= 1 ? 0 : step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3;
    QFont f = p->font();
    f.setPixelSize(10);
    p->setFont(f);
    QColor minor = m_color;
    minor.setAlpha(90);
    const double sub = step / 5;
    for (double t = std::floor(m_v0 / sub) * sub; t <= m_v1; t += sub) {
        const double x = (t - m_v0) / spx;
        const bool major = std::fabs(t / step - std::round(t / step)) < 1e-6;
        p->setPen(QPen(major ? m_color : minor, 1));
        p->drawLine(QPointF(x + 0.5, major ? h * 0.45 : h * 0.72), QPointF(x + 0.5, h));
        if (major)
            p->drawText(QPointF(x + 3, h * 0.45), format(t, dec));
    }
}
