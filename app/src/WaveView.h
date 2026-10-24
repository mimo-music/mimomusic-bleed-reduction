// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// One audio file's waveform between viewStart and viewEnd (seconds), at any
// zoom (min/max per pixel from the cache's pyramid; single samples when
// zoomed in far). Normalized to the file's peak by default; dB scale on
// request (shows quiet leak). Passages tint the background by kind.
#include "AudioCache.h"

#include <QColor>
#include <QQuickPaintedItem>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>

class WaveView : public QQuickPaintedItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString source READ source WRITE setSource NOTIFY sourceChanged)
    Q_PROPERTY(double duration READ duration NOTIFY sourceChanged)
    Q_PROPERTY(double peakDb READ peakDb NOTIFY sourceChanged)
    Q_PROPERTY(QString error READ error NOTIFY sourceChanged)
    Q_PROPERTY(double viewStart MEMBER m_v0 NOTIFY repaintNeeded)
    Q_PROPERTY(double viewEnd MEMBER m_v1 NOTIFY repaintNeeded)
    Q_PROPERTY(bool normalize MEMBER m_norm NOTIFY repaintNeeded)
    Q_PROPERTY(bool dbScale MEMBER m_db NOTIFY repaintNeeded)
    Q_PROPERTY(double dbRange MEMBER m_dbRange NOTIFY repaintNeeded)
    Q_PROPERTY(QColor color MEMBER m_color NOTIFY repaintNeeded)
    Q_PROPERTY(QColor backColor MEMBER m_back NOTIFY repaintNeeded)
    Q_PROPERTY(QColor lineColor MEMBER m_line NOTIFY repaintNeeded)
    Q_PROPERTY(QVariantList passages MEMBER m_passages NOTIFY repaintNeeded)
    Q_PROPERTY(QStringList kinds MEMBER m_kinds NOTIFY repaintNeeded)   // a passage's colour: its kind's place here
    Q_PROPERTY(double tint MEMBER m_tint NOTIFY repaintNeeded)
    Q_PROPERTY(bool spectral MEMBER m_spectral NOTIFY repaintNeeded)   // colour by frequency (Mixxx RGB)
    // raised when the files may have been rewritten under the same name (a render): read again if so
    Q_PROPERTY(int revision READ revision WRITE setRevision NOTIFY repaintNeeded)
public:
    explicit WaveView(QQuickItem *parent = nullptr);
    void paint(QPainter *p) override;
    QString source() const { return m_source; }
    void setSource(const QString &s);
    int revision() const { return m_rev; }
    void setRevision(int r);
    double duration() const { return m_clip ? m_clip->duration() : 0.0; }
    double peakDb() const;
    QString error() const { return m_clip ? m_clip->error : QString(); }
    static QColor tagColor(int i);     // the tag palette (same as Theme.tagColor)

signals:
    void sourceChanged();
    void repaintNeeded();

private:
    double y(float v, double mid) const;
    QString m_source;
    int m_rev = 0;
    ClipPtr m_clip;
    double m_v0 = 0, m_v1 = 1, m_dbRange = 54, m_tint = 0.13;
    bool m_norm = true, m_db = false, m_spectral = false;
    QColor m_color{120, 190, 200}, m_back{20, 21, 25}, m_line{44, 47, 54};
    QVariantList m_passages;
    QStringList m_kinds;
};

// time ruler over [viewStart, viewEnd]: ticks at a readable spacing, m:ss labels
class TimeRuler : public QQuickPaintedItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(double viewStart MEMBER m_v0 NOTIFY repaintNeeded)
    Q_PROPERTY(double viewEnd MEMBER m_v1 NOTIFY repaintNeeded)
    Q_PROPERTY(QColor color MEMBER m_color NOTIFY repaintNeeded)
    Q_PROPERTY(QColor backColor MEMBER m_back NOTIFY repaintNeeded)
public:
    explicit TimeRuler(QQuickItem *parent = nullptr);
    void paint(QPainter *p) override;
    Q_INVOKABLE static QString format(double t, int decimals = 2);

signals:
    void repaintNeeded();

private:
    double m_v0 = 0, m_v1 = 1;
    QColor m_color{150, 154, 162}, m_back{24, 25, 29};
};
