// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "AudioFile.h"

#include <QFile>
#include <sndfile.h>

Audio readMono(const QString &path)
{
    Audio a;
    SF_INFO info{};
    SNDFILE *f = sf_open(QFile::encodeName(path).constData(), SFM_READ, &info);
    if (!f) {
        a.error = QStringLiteral("%1: %2").arg(path, QString::fromUtf8(sf_strerror(nullptr)));
        return a;
    }
    a.rate = info.samplerate;
    const int ch = info.channels;
    a.data.resize(size_t(info.frames));
    std::vector<float> buf(size_t(8192) * ch);
    size_t pos = 0;
    while (pos < a.data.size()) {
        sf_count_t got = sf_readf_float(f, buf.data(), 8192);
        if (got <= 0)
            break;
        for (sf_count_t i = 0; i < got; ++i) {
            float s = 0;
            for (int c = 0; c < ch; ++c)
                s += buf[size_t(i) * ch + c];
            a.data[pos + size_t(i)] = s / float(ch);
        }
        pos += size_t(got);
    }
    a.data.resize(pos);
    sf_close(f);
    return a;
}

QString writeMonoFloat(const QString &path, const float *x, size_t n, int rate)
{
    SF_INFO info{};
    info.samplerate = rate;
    info.channels = 1;
    info.format = SF_FORMAT_WAV | SF_FORMAT_FLOAT;
    const QString tmp = path + QStringLiteral(".part");
    SNDFILE *f = sf_open(QFile::encodeName(tmp).constData(), SFM_WRITE, &info);
    if (!f)
        return QStringLiteral("%1: %2").arg(tmp, QString::fromUtf8(sf_strerror(nullptr)));
    sf_count_t w = sf_writef_float(f, x, sf_count_t(n));
    sf_close(f);
    if (w != sf_count_t(n)) {
        QFile::remove(tmp);
        return QStringLiteral("%1: short write").arg(path);
    }
    QFile::remove(path);
    if (!QFile::rename(tmp, path))
        return QStringLiteral("%1: rename failed").arg(path);
    return {};
}
