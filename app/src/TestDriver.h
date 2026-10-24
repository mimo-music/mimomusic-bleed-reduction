// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#pragma once
// For --gui-test: real mouse and key events into the window, so the self-test
// drives the views like a person (drags, Ctrl+click, wheel) instead of calling
// their functions. Coordinates are in the given item's own space.
#include <QObject>
#include <QPointF>

class QQuickItem;

class TestDriver : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;
    // mods: Qt.ControlModifier etc.
    Q_INVOKABLE void press(QQuickItem *item, double x, double y, int mods = 0, int button = 1);
    Q_INVOKABLE void move(QQuickItem *item, double x, double y, int mods = 0, int button = 1);
    Q_INVOKABLE void release(QQuickItem *item, double x, double y, int mods = 0, int button = 1);
    Q_INVOKABLE void click(QQuickItem *item, double x, double y, int mods = 0);
    // press, steps moves, release
    Q_INVOKABLE void drag(QQuickItem *item, double x0, double y0, double x1, double y1, int mods = 0, int steps = 8);
    Q_INVOKABLE void wheel(QQuickItem *item, double x, double y, int dy, int dx = 0, int mods = 0);
    Q_INVOKABLE void key(QQuickItem *anyItem, int key, int mods = 0, const QString &text = QString());
    // a file replaced as a tool would (the product test: a render rewriting a track's file)
    Q_INVOKABLE bool copyFile(const QString &from, const QString &to);

private:
    void mouse(int type, QQuickItem *item, double x, double y, int mods, int button, int buttons);
};
