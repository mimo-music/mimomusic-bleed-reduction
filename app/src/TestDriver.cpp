// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

#include "TestDriver.h"

#include <QCoreApplication>
#include <QFile>
#include <QGuiApplication>
#include <QKeyEvent>
#include <QMouseEvent>
#include <QQuickItem>
#include <QQuickWindow>
#include <QWheelEvent>
#include <QTest>

void TestDriver::mouse(int type, QQuickItem *item, double x, double y, int mods, int button, int buttons)
{
    if (!item || !item->window())
        return;
    const QPointF scene = item->mapToScene(QPointF(x, y));
    const QPointF global = item->window()->mapToGlobal(scene);
    QMouseEvent e(QEvent::Type(type), scene, scene, global, Qt::MouseButton(button), Qt::MouseButtons(buttons),
                  Qt::KeyboardModifiers(mods));
    QCoreApplication::sendEvent(item->window(), &e);
    QCoreApplication::processEvents();
}

void TestDriver::press(QQuickItem *item, double x, double y, int mods, int button)
{
    mouse(QEvent::MouseButtonPress, item, x, y, mods, button, button);
}

void TestDriver::move(QQuickItem *item, double x, double y, int mods, int button)
{
    mouse(QEvent::MouseMove, item, x, y, mods, Qt::NoButton, button);
}

void TestDriver::release(QQuickItem *item, double x, double y, int mods, int button)
{
    mouse(QEvent::MouseButtonRelease, item, x, y, mods, button, Qt::NoButton);
}

void TestDriver::click(QQuickItem *item, double x, double y, int mods)
{
    press(item, x, y, mods);
    release(item, x, y, mods);
}

void TestDriver::drag(QQuickItem *item, double x0, double y0, double x1, double y1, int mods, int steps)
{
    press(item, x0, y0, mods);
    for (int i = 1; i <= steps; ++i)
        move(item, x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, mods);
    release(item, x1, y1, mods);
}

void TestDriver::wheel(QQuickItem *item, double x, double y, int dy, int dx, int mods)
{
    if (!item || !item->window())
        return;
    const QPointF scene = item->mapToScene(QPointF(x, y));
    QWheelEvent e(scene, item->window()->mapToGlobal(scene), QPoint(), QPoint(dx, dy), Qt::NoButton,
                  Qt::KeyboardModifiers(mods), Qt::NoScrollPhase, false);
    QCoreApplication::sendEvent(item->window(), &e);
    QCoreApplication::processEvents();
}

void TestDriver::key(QQuickItem *anyItem, int key, int mods, const QString &)
{
    // QTest goes through the shortcut map like a real key press (sendEvent would not)
    if (!anyItem || !anyItem->window())
        return;
    QTest::keyClick(anyItem->window(), Qt::Key(key), Qt::KeyboardModifiers(mods));
    QCoreApplication::processEvents();
}

bool TestDriver::copyFile(const QString &from, const QString &to)
{
    QFile::remove(to + QStringLiteral(".part"));
    return QFile::copy(from, to + QStringLiteral(".part")) && QFile::remove(to) && QFile::rename(to + QStringLiteral(".part"), to);
}
