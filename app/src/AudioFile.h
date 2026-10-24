// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// Reading and writing mono audio with libsndfile (WAV/FLAC/AIFF..., any PCM or float).
#include <QString>
#include <vector>

struct Audio {
    std::vector<float> data;   // mono (channels averaged)
    int rate = 0;
    QString error;             // empty when it worked
};

Audio readMono(const QString &path);
// float 32-bit WAV; returns an error message or an empty string
QString writeMonoFloat(const QString &path, const float *x, size_t n, int rate);
