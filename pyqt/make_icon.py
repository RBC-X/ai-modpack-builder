"""Render the launcher's reference green-bolt mark and save it as .ico.

Run: pyqt/.venv/Scripts/python pyqt/make_icon.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap  # noqa: E402

app = QGuiApplication(sys.argv)

SIZE = 256
pix = QPixmap(SIZE, SIZE)
pix.fill(Qt.GlobalColor.transparent)

p = QPainter(pix)
p.setRenderHint(QPainter.RenderHint.Antialiasing)

# Rounded green-black tile, matching the mark in the launcher sidebar.
bg = QPainterPath()
bg.addRoundedRect(18, 18, SIZE - 36, SIZE - 36, 54, 54)
p.fillPath(bg, QColor("#132A1E"))
p.setPen(QPen(QColor("#267047"), 6))
p.drawPath(bg)

# Filled lightning bolt from the same 24x24 geometry used in the UI.
scale = 7.2
ox, oy = 41.5, 48.0
points = [(13, 2), (3, 14), (12, 14), (11, 22), (21, 10), (12, 10)]
bolt = QPainterPath()
bolt.moveTo(QPointF(ox + points[0][0] * scale, oy + points[0][1] * scale))
for x, y in points[1:]:
    bolt.lineTo(QPointF(ox + x * scale, oy + y * scale))
bolt.closeSubpath()
p.fillPath(bolt, QColor("#39B86A"))
p.end()

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
ok = pix.save(out, "ICO")
print(f"icon {'saved' if ok else 'FAILED'}: {out}")
sys.exit(0 if ok else 1)
