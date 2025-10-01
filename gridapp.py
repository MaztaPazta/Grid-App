# Last War Survivor — Alliance Map Tool (Python, PySide6)
# ------------------------------------------------------
#
# Fixes in this version
# - Removed Space modifier (Qt has none). **Pan = Middle mouse** or **Shift + Left**.
# - Removed all drag-and-drop code; placement uses a **preview tool**.
# - Fixed dataclass mutable default (`QColor`) using `default_factory`.
# - Replaced deprecated `.pos()` with `.position()`.
# - Objects & preview are **above** the grid; placement is **centered under cursor**.
# - Status coordinates use **1,1 at bottom-left**.
# - Double-click items in **Objects** to edit **default name** & **color**.
#
# Run
# - Install: `pip install PySide6`
# - Start: `python app.py`
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

from PySide6.QtCore import (
    QEvent,
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QFont,
    QGuiApplication,
    QCursor,
    QPainter,
    QPen,
    QColor,
    QIcon,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QInputDialog,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)


# ----------------------------- Config ---------------------------------
GRID_CELLS = 999  # 999x999
CELL_SIZE = 20    # pixels per cell (zoom lets you navigate efficiently)
GRID_COLOR = Qt.gray
GRID_THICK_COLOR = Qt.darkGray
BACKGROUND_COLOR = Qt.white


@dataclass
class ObjectSpec:
    name: str
    size_w: int = 1  # width in cells
    size_h: int = 1  # height in cells
    fill: QColor = field(default_factory=lambda: QColor(Qt.lightGray))
    limit: Optional[int] = None
    limit_key: Optional[str] = None

    def __post_init__(self):
        if self.limit_key is None:
            self.limit_key = self.name


@dataclass
class ZoneSpec:
    name: str
    size_w: int = 1
    size_h: int = 1
    fill: QColor = field(default_factory=lambda: QColor(255, 0, 0, 60))
    edge: QColor = field(default_factory=lambda: QColor(Qt.red))


DEFAULT_CATEGORIES: dict[str, list[ObjectSpec]] = {
    "Alliance": [
        ObjectSpec("R1", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("R2", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("R3", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("R4", 3, 3, QColor(Qt.lightGray), limit=10, limit_key="R4"),
        ObjectSpec("R5", 3, 3, QColor(Qt.lightGray), limit=1, limit_key="R5"),
        ObjectSpec("Base", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("MG", 3, 3, QColor(Qt.lightGray), limit=1, limit_key="MG"),
        ObjectSpec("Furnace", 3, 3, QColor(Qt.lightGray), limit=1, limit_key="Furnace"),
    ]
}


DEFAULT_ZONE_FILL = QColor(255, 0, 0, 60)
DEFAULT_ZONE_EDGE = QColor(Qt.red)


def clone_spec(spec: ObjectSpec) -> ObjectSpec:
    return ObjectSpec(
        spec.name,
        spec.size_w,
        spec.size_h,
        QColor(spec.fill),
        spec.limit,
        spec.limit_key,
    )


# ----------------------------- UI Helpers ------------------------------
def create_color_icon(color: QColor, size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QBrush(color))
    pen = QPen(Qt.black)
    pen.setWidth(1)
    painter.setPen(pen)
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.end()
    return QIcon(pixmap)


def create_zone_icon(fill: QColor, edge: QColor, size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QBrush(fill))
    pen = QPen(edge)
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawRect(1, 1, size - 3, size - 3)
    painter.end()
    return QIcon(pixmap)


# ----------------------------- Map Items -------------------------------
class MapObject(QGraphicsItemGroup):
    def __init__(self, spec: ObjectSpec, top_left: QPointF, cell_size: int):
        super().__init__()
        self.spec = spec
        self.cell_size = cell_size
        self._last_valid_pos = QPointF(top_left)

        w = spec.size_w * cell_size
        h = spec.size_h * cell_size
        rect_item = QGraphicsRectItem(0, 0, w, h)
        rect_item.setBrush(QBrush(spec.fill))
        rect_item.setPen(QPen(Qt.black, 1))

        label = QGraphicsSimpleTextItem(spec.name)
        label.setBrush(Qt.black)
        font = QFont()
        font.setPointSizeF(max(8.0, cell_size * 0.5))
        label.setFont(font)
        # center text
        label_rect = label.boundingRect()
        label.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

        self.addToGroup(rect_item)
        self.addToGroup(label)
        self.rect_item = rect_item
        self.label_item = label

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        # Ensure above any future overlays; grid is drawn in background
        self.setZValue(1000)
        self.setPos(top_left)

    def bounding_rect_scene(self) -> QRectF:
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        return QRectF(self.pos().x(), self.pos().y(), w, h)

    def mousePressEvent(self, event):
        self._drag_start_pos = QPointF(self.pos())
        super().mousePressEvent(event)

    def updateLabelLayout(self):
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        label_rect = self.label_item.boundingRect()
        self.label_item.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

    def mouseDoubleClickEvent(self, event):
        self._prompt_rename()
        super().mouseDoubleClickEvent(event)

    def _prompt_rename(self):
        new_name, ok = QInputDialog.getText(
            None, "Edit object", "Enter name:", text=self.label_item.text()
        )
        if ok and new_name.strip():
            final_name = new_name.strip()
            self.spec.name = final_name
            self.label_item.setText(final_name)
            self.updateLabelLayout()
            return True
        return False

    def _prompt_change_color(self):
        color = QColorDialog.getColor(self.spec.fill, None, "Choose color")
        if color.isValid():
            self.spec.fill = QColor(color)
            self.rect_item.setBrush(QBrush(self.spec.fill))
            return True
        return False

    def _prompt_resize(self):
        scene = self.scene()
        max_size = GRID_CELLS
        if isinstance(scene, MapScene):
            max_size = scene.cells

        old_w = self.spec.size_w
        old_h = self.spec.size_h
        width, ok_w = QInputDialog.getInt(
            None,
            "Width",
            "Width (cells):",
            value=self.spec.size_w,
            min=1,
            max=max_size,
        )
        height, ok_h = (self.spec.size_h, False)
        if ok_w:
            height, ok_h = QInputDialog.getInt(
                None,
                "Height",
                "Height (cells):",
                value=self.spec.size_h,
                min=1,
                max=max_size,
            )

        if not (ok_w and ok_h):
            return False

        self.spec.size_w = width
        self.spec.size_h = height
        if isinstance(scene, MapScene):
            self.cell_size = scene.cell_size
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        self.rect_item.setRect(0, 0, w, h)
        self.updateLabelLayout()
        if isinstance(scene, MapScene):
            scene.snap_items_to_grid([self])
            if not scene.is_object_position_free(self):
                self.spec.size_w = old_w
                self.spec.size_h = old_h
                self.cell_size = scene.cell_size
                w = self.spec.size_w * self.cell_size
                h = self.spec.size_h * self.cell_size
                self.rect_item.setRect(0, 0, w, h)
                self.updateLabelLayout()
                scene.snap_items_to_grid([self])
                QMessageBox.information(
                    None,
                    "Overlap",
                    "Cannot resize object because it would overlap another object.",
                )
                return False
            self._last_valid_pos = QPointF(self.pos())
        else:
            current_top_left = self.pos()
            snapped_x = round(current_top_left.x() / self.cell_size) * self.cell_size
            snapped_y = round(current_top_left.y() / self.cell_size) * self.cell_size
            self.setPos(QPointF(snapped_x, snapped_y))
        return True

    def contextMenuEvent(self, event):
        menu = QMenu()
        rename_action = menu.addAction("Rename")
        color_action = menu.addAction("Change Color")
        size_action = menu.addAction("Resize")
        chosen = menu.exec(event.screenPos())
        if chosen == rename_action:
            self._prompt_rename()
        elif chosen == color_action:
            self._prompt_change_color()
        elif chosen == size_action:
            self._prompt_resize()
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is None:
            return
        if isinstance(scene, MapScene):
            map_objects = [item for item in scene.selectedItems() if isinstance(item, MapObject)]
            if not map_objects:
                map_objects = [self]
            scene.snap_items_to_grid(map_objects)
            for obj in map_objects:
                if not scene.is_object_position_free(obj):
                    # revert to last valid position
                    revert_pos = getattr(obj, "_drag_start_pos", obj._last_valid_pos)
                    obj.setPos(revert_pos)
                    scene.snap_items_to_grid([obj])
                    obj._last_valid_pos = QPointF(obj.pos())
                else:
                    obj._last_valid_pos = QPointF(obj.pos())
        else:
            cs = self.cell_size
            current_top_left = self.pos()
            snapped_x = round(current_top_left.x() / cs) * cs
            snapped_y = round(current_top_left.y() / cs) * cs
            self.setPos(QPointF(snapped_x, snapped_y))


class PreviewObject(QGraphicsItemGroup):
    """Translucent preview that follows the cursor and snaps to grid (centered)."""
    def __init__(self, spec: ObjectSpec, cell_size: int):
        super().__init__()
        self.spec = spec
        self.cell_size = cell_size

        w = spec.size_w * cell_size
        h = spec.size_h * cell_size
        rect_item = QGraphicsRectItem(0, 0, w, h)
        rect_item.setBrush(QBrush(spec.fill))
        pen = QPen(Qt.black)
        pen.setStyle(Qt.DashLine)
        rect_item.setPen(pen)

        label = QGraphicsSimpleTextItem(spec.name)
        font = QFont()
        font.setPointSizeF(max(8.0, cell_size * 0.5))
        label.setFont(font)
        label_rect = label.boundingRect()
        label.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

        self.addToGroup(rect_item)
        self.addToGroup(label)
        self.rect_item = rect_item
        self.label_item = label

        self.setOpacity(0.4)
        self.setZValue(1_000_000)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def update_for_cell_size(self, cell_size: int):
        self.cell_size = cell_size
        w = self.spec.size_w * cell_size
        h = self.spec.size_h * cell_size
        self.rect_item.setRect(0, 0, w, h)
        font = self.label_item.font()
        font.setPointSizeF(max(8.0, cell_size * 0.5))
        self.label_item.setFont(font)
        label_rect = self.label_item.boundingRect()
        self.label_item.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)


class ZoneCoordinateDialog(QDialog):
    def __init__(
        self,
        max_cells: int,
        bottom_left: tuple[int, int],
        top_right: tuple[int, int],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Set Zone Coordinates")

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Enter cell coordinates (0-based) using a bottom-left origin for Y."
            )
        )

        self.bottom_left_x = QSpinBox(self)
        self.bottom_left_x.setRange(0, max_cells - 1)
        self.bottom_left_x.setValue(bottom_left[0])

        self.bottom_left_y = QSpinBox(self)
        self.bottom_left_y.setRange(0, max_cells - 1)
        self.bottom_left_y.setValue(bottom_left[1])

        self.top_right_x = QSpinBox(self)
        self.top_right_x.setRange(0, max_cells - 1)
        self.top_right_x.setValue(top_right[0])

        self.top_right_y = QSpinBox(self)
        self.top_right_y.setRange(0, max_cells - 1)
        self.top_right_y.setValue(top_right[1])

        self.top_right_x.setMinimum(bottom_left[0])
        self.top_right_y.setMinimum(bottom_left[1])

        self.bottom_left_x.valueChanged.connect(self.top_right_x.setMinimum)
        self.bottom_left_y.valueChanged.connect(self.top_right_y.setMinimum)

        bl_row = QHBoxLayout()
        bl_row.addWidget(QLabel("Bottom-left X:"))
        bl_row.addWidget(self.bottom_left_x)
        layout.addLayout(bl_row)

        bl_y_row = QHBoxLayout()
        bl_y_row.addWidget(QLabel("Bottom-left Y:"))
        bl_y_row.addWidget(self.bottom_left_y)
        layout.addLayout(bl_y_row)

        tr_row = QHBoxLayout()
        tr_row.addWidget(QLabel("Top-right X:"))
        tr_row.addWidget(self.top_right_x)
        layout.addLayout(tr_row)

        tr_y_row = QHBoxLayout()
        tr_y_row.addWidget(QLabel("Top-right Y:"))
        tr_y_row.addWidget(self.top_right_y)
        layout.addLayout(tr_y_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_coordinates(self) -> tuple[int, int, int, int]:
        return (
            self.bottom_left_x.value(),
            self.bottom_left_y.value(),
            self.top_right_x.value(),
            self.top_right_y.value(),
        )


class MapZone(QGraphicsItemGroup):
    def __init__(self, spec: ZoneSpec, top_left: QPointF, cell_size: int):
        super().__init__()
        self.spec = spec
        self.cell_size = cell_size

        w = spec.size_w * cell_size
        h = spec.size_h * cell_size

        rect_item = QGraphicsRectItem(0, 0, w, h)
        rect_item.setBrush(QBrush(spec.fill))
        rect_item.setPen(QPen(spec.edge, 2))

        label = QGraphicsSimpleTextItem(spec.name)
        label.setBrush(Qt.black)
        font = QFont()
        font.setPointSizeF(max(8.0, cell_size * 0.4))
        label.setFont(font)
        label_rect = label.boundingRect()
        label.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

        self.addToGroup(rect_item)
        self.addToGroup(label)
        self.rect_item = rect_item
        self.label_item = label

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(100)  # below objects but above background fill
        self.setPos(top_left)

    def bounding_rect_scene(self) -> QRectF:
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        return QRectF(self.pos().x(), self.pos().y(), w, h)

    def updateLabelLayout(self):
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        label_rect = self.label_item.boundingRect()
        self.label_item.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

    def mouseDoubleClickEvent(self, event):
        self._prompt_rename()
        super().mouseDoubleClickEvent(event)

    def _emit_zone_updated(self):
        scene = self.scene()
        if isinstance(scene, MapScene):
            scene.zone_updated.emit(self)

    def _prompt_rename(self):
        new_name, ok = QInputDialog.getText(
            None, "Edit zone", "Enter name:", text=self.label_item.text()
        )
        if ok and new_name.strip():
            final_name = new_name.strip()
            self.spec.name = final_name
            self.label_item.setText(final_name)
            self.updateLabelLayout()
            self._emit_zone_updated()
            return True
        return False

    def _prompt_change_fill(self):
        fill_color = QColorDialog.getColor(self.spec.fill, None, "Choose fill color")
        if fill_color.isValid():
            self.spec.fill = QColor(fill_color)
            self.rect_item.setBrush(QBrush(self.spec.fill))
            self._emit_zone_updated()
            return True
        return False

    def _prompt_change_edge(self):
        edge_color = QColorDialog.getColor(self.spec.edge, None, "Choose edge color")
        if edge_color.isValid():
            self.spec.edge = QColor(edge_color)
            pen = self.rect_item.pen()
            pen.setColor(self.spec.edge)
            self.rect_item.setPen(pen)
            self._emit_zone_updated()
            return True
        return False

    def _prompt_resize(self):
        scene = self.scene()
        max_size = GRID_CELLS
        if isinstance(scene, MapScene):
            max_size = scene.cells

        width, ok_w = QInputDialog.getInt(
            None,
            "Width",
            "Width (cells):",
            value=self.spec.size_w,
            min=1,
            max=max_size,
        )
        height, ok_h = (self.spec.size_h, False)
        if ok_w:
            height, ok_h = QInputDialog.getInt(
                None,
                "Height",
                "Height (cells):",
                value=self.spec.size_h,
                min=1,
                max=max_size,
            )

        if not (ok_w and ok_h):
            return False

        self.spec.size_w = width
        self.spec.size_h = height
        if isinstance(scene, MapScene):
            self.cell_size = scene.cell_size
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        self.rect_item.setRect(0, 0, w, h)
        self.updateLabelLayout()
        if isinstance(scene, MapScene):
            scene.snap_items_to_grid([self])
        else:
            current_top_left = self.pos()
            snapped_x = round(current_top_left.x() / self.cell_size) * self.cell_size
            snapped_y = round(current_top_left.y() / self.cell_size) * self.cell_size
            self.setPos(QPointF(snapped_x, snapped_y))

        self._emit_zone_updated()
        return True

    def _prompt_set_coordinates(self):
        scene = self.scene()
        if scene is None:
            return False
        cs = self.cell_size
        max_cells = GRID_CELLS
        if isinstance(scene, MapScene):
            cs = scene.cell_size
            max_cells = scene.cells

        current_top_left = self.pos()
        x_cells = int(round(current_top_left.x() / cs))
        y_cells = int(round(current_top_left.y() / cs))
        width_cells = self.spec.size_w
        height_cells = self.spec.size_h
        bottom_left_x = x_cells
        # Convert top-origin y to bottom-origin coordinates
        max_index = max_cells - 1
        bottom_left_y = max_index - (y_cells + height_cells - 1)
        top_right_x = bottom_left_x + width_cells - 1
        top_right_y = bottom_left_y + height_cells - 1

        bottom_left = (bottom_left_x, bottom_left_y)
        top_right = (top_right_x, top_right_y)

        dialog = ZoneCoordinateDialog(max_cells, bottom_left, top_right)
        if dialog.exec() != QDialog.Accepted:
            return False

        x_bl, y_bl, x_tr, y_tr = dialog.get_coordinates()
        if x_tr < x_bl or y_tr < y_bl:
            QMessageBox.warning(
                None,
                "Invalid coordinates",
                "Top-right coordinates must be greater than or equal to bottom-left.",
            )
            return False

        if not (0 <= x_tr < max_cells and 0 <= y_tr < max_cells):
            QMessageBox.warning(
                None,
                "Coordinates out of bounds",
                "The specified zone extends beyond the map bounds.",
            )
            return False

        width = (x_tr - x_bl) + 1
        height = (y_tr - y_bl) + 1
        if width <= 0 or height <= 0:
            QMessageBox.warning(
                None,
                "Invalid size",
                "Zone must be at least 1x1 cell.",
            )
            return False

        top_left_y_cells = max_cells - y_tr - 1
        if top_left_y_cells < 0:
            QMessageBox.warning(
                None,
                "Coordinates out of bounds",
                "The specified zone extends beyond the map bounds.",
            )
            return False

        self.spec.size_w = width
        self.spec.size_h = height
        if isinstance(scene, MapScene):
            self.cell_size = scene.cell_size
            cs = self.cell_size

        w = self.spec.size_w * cs
        h = self.spec.size_h * cs
        self.rect_item.setRect(0, 0, w, h)
        self.updateLabelLayout()

        new_pos = QPointF(x_bl * cs, top_left_y_cells * cs)
        if isinstance(scene, MapScene):
            clamped = scene._clamp_top_left(new_pos.x(), new_pos.y(), w, h)
            self.setPos(clamped)
        else:
            self.setPos(new_pos)

        self._emit_zone_updated()
        return True

    def _trigger_redraw(self):
        scene = self.scene()
        if scene is None:
            return False
        main_window = None
        for view in scene.views():
            window = view.window()
            if isinstance(window, MainWindow):
                main_window = window
                break
        if main_window is None:
            return False
        main_window.begin_zone_redraw(self)
        return True

    def contextMenuEvent(self, event):
        menu = QMenu()
        rename_action = menu.addAction("Rename")
        fill_action = menu.addAction("Change Fill Color")
        edge_action = menu.addAction("Change Edge Color")
        size_action = menu.addAction("Resize")
        coord_action = menu.addAction("Set Coordinates...")
        redraw_action = menu.addAction("Redraw Zone")
        chosen = menu.exec(event.screenPos())
        if chosen == rename_action:
            self._prompt_rename()
        elif chosen == fill_action:
            self._prompt_change_fill()
        elif chosen == edge_action:
            self._prompt_change_edge()
        elif chosen == size_action:
            self._prompt_resize()
        elif chosen == coord_action:
            self._prompt_set_coordinates()
        elif chosen == redraw_action:
            self._trigger_redraw()
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is None:
            return
        if isinstance(scene, MapScene):
            zones = [item for item in scene.selectedItems() if isinstance(item, MapZone)]
            if not zones:
                zones = [self]
            scene.snap_items_to_grid(zones)
        else:
            cs = self.cell_size
            current_top_left = self.pos()
            snapped_x = round(current_top_left.x() / cs) * cs
            snapped_y = round(current_top_left.y() / cs) * cs
            self.setPos(QPointF(snapped_x, snapped_y))


class GridLinesItem(QGraphicsItem):
    def __init__(self, map_scene: "MapScene"):
        super().__init__()
        self.map_scene = map_scene
        self._rect = QRectF(0, 0, map_scene.scene_width(), map_scene.scene_height())
        self.setZValue(500)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(False)

    def update_geometry(self):
        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, self.map_scene.scene_width(), self.map_scene.scene_height())

    def boundingRect(self) -> QRectF:
        return self._rect

    def contains(self, point: QPointF) -> bool:
        return False

    def paint(self, painter: QPainter, option, widget=None):
        if not self.map_scene.show_grid:
            return
        rect = option.exposedRect if option is not None else self._rect
        rect = rect.intersected(self._rect)
        cs = self.map_scene.cell_size
        left = int(math.floor(rect.left() / cs))
        right = int(math.ceil(rect.right() / cs))
        top = int(math.floor(rect.top() / cs))
        bottom = int(math.ceil(rect.bottom() / cs))

        pen_fine = QPen(GRID_COLOR)
        pen_fine.setWidth(1)
        painter.setPen(pen_fine)
        for x in range(left, right + 1):
            px = x * cs
            painter.drawLine(px, rect.top(), px, rect.bottom())
        for y in range(top, bottom + 1):
            py = y * cs
            painter.drawLine(rect.left(), py, rect.right(), py)

        pen_thick = QPen(GRID_THICK_COLOR)
        pen_thick.setWidth(2)
        painter.setPen(pen_thick)
        for x in range(left, right + 1):
            if x % 10 == 0:
                px = x * cs
                painter.drawLine(px, rect.top(), px, rect.bottom())
        for y in range(top, bottom + 1):
            if y % 10 == 0:
                py = y * cs
                painter.drawLine(rect.left(), py, rect.right(), py)


# ----------------------------- Scene/View ------------------------------
class MapScene(QGraphicsScene):
    zone_created = Signal(object)
    zone_updated = Signal(object)
    zone_removed = Signal(object)
    zone_redraw_finished = Signal(object)

    def __init__(self, cells: int, cell_size: int, parent=None):
        super().__init__(parent)
        self.cells = cells
        self.cell_size = cell_size
        size_px = cells * cell_size
        self.setSceneRect(0, 0, size_px, size_px)
        self.show_grid = True
        self.setBackgroundBrush(QBrush(BACKGROUND_COLOR))
        self.setItemIndexMethod(QGraphicsScene.NoIndex)

        # Placement tool state
        self.active_spec: Optional[ObjectSpec] = None
        self.preview_item: Optional[QGraphicsItemGroup] = None
        self.grid_item = GridLinesItem(self)
        self.addItem(self.grid_item)
        self.grid_item.setVisible(self.show_grid)

        self.zone_draw_mode = False
        self.zone_draw_start: Optional[QPointF] = None
        self.zone_draw_preview: Optional[QGraphicsRectItem] = None
        self.zone_hover_indicator: Optional[QGraphicsRectItem] = None
        self._zone_counter = 0
        self._zones: list[MapZone] = []
        self._zone_redraw_target: Optional[MapZone] = None
        self._zone_redraw_hidden_target = False

    # --- Helpers ---
    def scene_width(self) -> float:
        return float(self.sceneRect().width())

    def scene_height(self) -> float:
        return float(self.sceneRect().height())

    def _clamp_top_left(self, x: float, y: float, w: float, h: float) -> QPointF:
        x = max(0, min(self.scene_width() - w, x))
        y = max(0, min(self.scene_height() - h, y))
        return QPointF(x, y)

    def _top_left_from_center_snap(self, scene_pos: QPointF) -> QPointF:
        cs = self.cell_size
        spec = self.active_spec
        if spec is None:
            return QPointF(0, 0)
        w = spec.size_w * cs
        h = spec.size_h * cs
        desired_top_left_x = scene_pos.x() - w / 2
        desired_top_left_y = scene_pos.y() - h / 2
        snapped_x = round(desired_top_left_x / cs) * cs
        snapped_y = round(desired_top_left_y / cs) * cs
        return self._clamp_top_left(snapped_x, snapped_y, w, h)

    def snap_items_to_grid(self, objects: Iterable[QGraphicsItemGroup]):
        cs = self.cell_size
        for obj in objects:
            if not isinstance(obj, (MapObject, MapZone)):
                continue
            obj.cell_size = cs
            w = obj.spec.size_w * cs
            h = obj.spec.size_h * cs
            current_top_left = obj.pos()
            snapped_x = round(current_top_left.x() / cs) * cs
            snapped_y = round(current_top_left.y() / cs) * cs
            top_left = self._clamp_top_left(snapped_x, snapped_y, w, h)
            obj.setPos(top_left)

    def is_area_free_for_object(self, rect: QRectF, ignore_item: Optional[QGraphicsItemGroup] = None) -> bool:
        for item in self.items():
            if not isinstance(item, MapObject):
                continue
            if item is ignore_item:
                continue
            item_rect = item.bounding_rect_scene()
            if rect.intersects(item_rect):
                return False
        return True

    def is_object_position_free(self, obj: MapObject) -> bool:
        rect = obj.bounding_rect_scene()
        return self.is_area_free_for_object(rect, obj)

    def count_objects_with_key(self, key: Optional[str]) -> int:
        if not key:
            return 0
        count = 0
        for item in self.items():
            if isinstance(item, MapObject) and item.spec.limit_key == key:
                count += 1
        return count

    # --- Placement tool API ---
    def set_active_spec(self, spec: Optional[ObjectSpec]):
        if self.preview_item is not None:
            self.removeItem(self.preview_item)
            self.preview_item = None
        self.active_spec = spec
        if spec is not None:
            self.preview_item = PreviewObject(spec, self.cell_size)
            self.addItem(self.preview_item)

    def cancel_placement(self):
        self.set_active_spec(None)

    def update_preview(self, scene_pos: QPointF):
        if self.active_spec is None or self.preview_item is None:
            return
        self.preview_item.setVisible(True)
        self.preview_item.setPos(self._top_left_from_center_snap(scene_pos))

    def place_active_at(self, scene_pos: QPointF) -> Optional[QGraphicsItemGroup]:
        if self.active_spec is None:
            return None
        if self.active_spec.limit is not None:
            limit_key = self.active_spec.limit_key or self.active_spec.name
            existing = self.count_objects_with_key(limit_key)
            if existing >= self.active_spec.limit:
                QMessageBox.information(
                    None,
                    "Limit reached",
                    f"Cannot place more than {self.active_spec.limit} instance(s) of {limit_key}.",
                )
                return None
        pos = self._top_left_from_center_snap(scene_pos)
        rect = QRectF(
            pos.x(),
            pos.y(),
            self.active_spec.size_w * self.cell_size,
            self.active_spec.size_h * self.cell_size,
        )
        if not self.is_area_free_for_object(rect):
            QMessageBox.information(None, "Overlap", "Cannot place object on top of another object.")
            return None
        obj = MapObject(clone_spec(self.active_spec), pos, self.cell_size)
        self.addItem(obj)
        obj.updateLabelLayout()
        obj._last_valid_pos = QPointF(obj.pos())
        return obj

    def _next_zone_name(self) -> str:
        self._zone_counter += 1
        return f"Zone {self._zone_counter}"

    def prepare_zone_redraw(self, zone: MapZone):
        self._zone_redraw_target = zone
        self.zone_draw_start = None
        if self.zone_draw_preview is not None:
            self.zone_draw_preview.setVisible(False)
        if self.zone_hover_indicator is not None:
            self.zone_hover_indicator.setVisible(True)
        self._zone_redraw_hidden_target = False

    def set_zone_draw_mode(self, enabled: bool):
        if self.zone_draw_mode == enabled:
            if not enabled:
                self._zone_redraw_target = None
            return
        self.zone_draw_mode = enabled
        if not enabled:
            self.cancel_zone_draw()
            self.hide_zone_hover()
            self._zone_redraw_target = None
        else:
            self.zone_draw_start = None
            self.show_zone_hover()

    def snap_to_grid_corner(self, scene_pos: QPointF) -> QPointF:
        cs = self.cell_size
        x = round(scene_pos.x() / cs) * cs
        y = round(scene_pos.y() / cs) * cs
        x = max(0, min(self.scene_width(), x))
        y = max(0, min(self.scene_height(), y))
        return QPointF(x, y)

    def is_drawing_zone(self) -> bool:
        return self.zone_draw_mode and self.zone_draw_start is not None

    def begin_zone_draw(self, start: QPointF):
        if not self.zone_draw_mode:
            return
        if self._zone_redraw_target is not None and not self._zone_redraw_hidden_target:
            self._zone_redraw_target.setVisible(False)
            self._zone_redraw_hidden_target = True
        self.zone_draw_start = start
        if self.zone_hover_indicator is not None:
            self.zone_hover_indicator.setVisible(False)
        if self.zone_draw_preview is None:
            preview = QGraphicsRectItem()
            preview.setBrush(QBrush(QColor(DEFAULT_ZONE_FILL)))
            pen = QPen(QColor(DEFAULT_ZONE_EDGE), 2)
            pen.setStyle(Qt.DashLine)
            preview.setPen(pen)
            preview.setOpacity(0.35)
            preview.setZValue(950)
            preview.setAcceptedMouseButtons(Qt.NoButton)
            self.zone_draw_preview = preview
            self.addItem(preview)
        self.zone_draw_preview.setVisible(True)
        rect = QRectF(start, start).normalized()
        self.zone_draw_preview.setRect(rect)

    def update_zone_draw(self, scene_pos: QPointF):
        if not self.is_drawing_zone() or self.zone_draw_preview is None:
            return
        end = self.snap_to_grid_corner(scene_pos)
        rect = QRectF(self.zone_draw_start, end).normalized()
        if rect.width() == 0 and rect.height() == 0:
            rect = QRectF(end, end)
        self.zone_draw_preview.setRect(rect)

    def finish_zone_draw(self, scene_pos: QPointF) -> Optional[MapZone]:
        if not self.is_drawing_zone():
            return None
        end = self.snap_to_grid_corner(scene_pos)
        start = self.zone_draw_start
        self.zone_draw_start = None
        if self.zone_draw_preview is not None:
            self.zone_draw_preview.setVisible(False)
        if self.zone_hover_indicator is not None:
            self.zone_hover_indicator.setVisible(True)

        self.update_zone_hover(end)
        if start == end:
            if self._zone_redraw_target is not None and self._zone_redraw_hidden_target:
                self._zone_redraw_target.setVisible(True)
                self._zone_redraw_hidden_target = False
            return None

        rect = QRectF(start, end).normalized()
        cs = self.cell_size
        width_cells = int(round(rect.width() / cs))
        height_cells = int(round(rect.height() / cs))
        if width_cells == 0 or height_cells == 0:
            if self._zone_redraw_target is not None and self._zone_redraw_hidden_target:
                self._zone_redraw_target.setVisible(True)
                self._zone_redraw_hidden_target = False
            return None

        top_left = QPointF(rect.left(), rect.top())
        if self._zone_redraw_target is not None:
            zone = self._zone_redraw_target
            zone.spec.size_w = width_cells
            zone.spec.size_h = height_cells
            zone.cell_size = self.cell_size
            w = zone.spec.size_w * self.cell_size
            h = zone.spec.size_h * self.cell_size
            zone.rect_item.setRect(0, 0, w, h)
            zone.updateLabelLayout()
            clamped = self._clamp_top_left(top_left.x(), top_left.y(), w, h)
            zone.setPos(clamped)
            zone.setVisible(True)
            self.zone_updated.emit(zone)
            self.zone_redraw_finished.emit(zone)
            self._zone_redraw_target = None
            self._zone_redraw_hidden_target = False
            return zone

        spec = ZoneSpec(
            self._next_zone_name(),
            width_cells,
            height_cells,
            QColor(DEFAULT_ZONE_FILL),
            QColor(DEFAULT_ZONE_EDGE),
        )
        zone = MapZone(spec, top_left, self.cell_size)
        self.addItem(zone)
        zone.updateLabelLayout()
        self._zones.append(zone)
        self.zone_created.emit(zone)
        return zone

    def cancel_zone_draw(self):
        self.zone_draw_start = None
        if self.zone_draw_preview is not None:
            self.zone_draw_preview.setVisible(False)
        if self.zone_draw_mode:
            self.show_zone_hover()
        else:
            self.hide_zone_hover()
        if self._zone_redraw_target is not None and self._zone_redraw_hidden_target:
            self._zone_redraw_target.setVisible(True)
        self._zone_redraw_hidden_target = False
        self._zone_redraw_target = None

    def update_zone_hover(self, scene_pos: QPointF):
        if not self.zone_draw_mode:
            return
        snapped = self.snap_to_grid_corner(scene_pos)
        if self.zone_hover_indicator is None:
            indicator = QGraphicsRectItem(0, 0, self.cell_size, self.cell_size)
            pen = QPen(QColor(DEFAULT_ZONE_EDGE))
            pen.setStyle(Qt.DotLine)
            pen.setWidth(2)
            indicator.setPen(pen)
            indicator.setBrush(Qt.NoBrush)
            indicator.setZValue(900)
            indicator.setAcceptedMouseButtons(Qt.NoButton)
            self.zone_hover_indicator = indicator
            self.addItem(indicator)
        rect = QRectF(0, 0, self.cell_size, self.cell_size)
        self.zone_hover_indicator.setRect(rect)
        self.zone_hover_indicator.setPos(snapped)
        self.zone_hover_indicator.setVisible(not self.is_drawing_zone())

    def hide_zone_hover(self):
        if self.zone_hover_indicator is not None:
            self.zone_hover_indicator.setVisible(False)

    def show_zone_hover(self):
        if self.zone_hover_indicator is not None:
            self.zone_hover_indicator.setVisible(True)

    def update_zone_draw_visuals(self):
        if self.zone_hover_indicator is not None:
            self.zone_hover_indicator.setRect(QRectF(0, 0, self.cell_size, self.cell_size))
        if self.zone_draw_preview is not None:
            pen = self.zone_draw_preview.pen()
            pen.setColor(QColor(DEFAULT_ZONE_EDGE))
            self.zone_draw_preview.setPen(pen)
            self.zone_draw_preview.setBrush(QBrush(QColor(DEFAULT_ZONE_FILL)))

    def remove_map_item(self, item: QGraphicsItemGroup):
        self.removeItem(item)
        if isinstance(item, MapZone):
            if item in self._zones:
                self._zones.remove(item)
            self.zone_removed.emit(item)

    # --- Painting ---
    def drawBackground(self, painter: QPainter, rect: QRectF):
        # Fill background; grid lines handled by dedicated item so they can appear above zones
        painter.fillRect(rect, QBrush(BACKGROUND_COLOR))


class MapView(QGraphicsView):
    def __init__(self, scene: MapScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self._panning = False
        self._pan_start = QPointF()
        self._rubber_selecting = False

    def _map_item_from_graphics_item(
        self, item: Optional[QGraphicsItem]
    ) -> Optional[QGraphicsItemGroup]:
        while item is not None and not isinstance(item, (MapObject, MapZone)):
            item = item.parentItem()
        return item if isinstance(item, (MapObject, MapZone)) else None

    def wheelEvent(self, event):
        # Zoom on wheel: Ctrl for fine steps
        delta = event.angleDelta().y()
        if delta == 0:
            return
        steps = delta / 240
        factor = 1.0 + (0.20 if not (event.modifiers() & Qt.ControlModifier) else 0.05) * steps
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        scene: MapScene = self.scene()
        if scene.zone_draw_mode:
            if event.button() == Qt.RightButton:
                scene_pos = self.mapToScene(event.position().toPoint())
                if scene.is_drawing_zone():
                    scene.cancel_zone_draw()
                    scene.update_zone_hover(scene_pos)
                else:
                    window = self.window()
                    if hasattr(window, "set_zone_draw_mode"):
                        window.set_zone_draw_mode(False)
                event.accept()
                return
            if event.button() == Qt.LeftButton:
                scene_pos = self.mapToScene(event.position().toPoint())
                snapped = scene.snap_to_grid_corner(scene_pos)
                scene.begin_zone_draw(snapped)
                event.accept()
                return
        if scene.active_spec is not None:
            window = self.window()
            if event.button() == Qt.RightButton:
                if hasattr(window, "cancel_active_placement"):
                    window.cancel_active_placement()
                else:
                    scene.cancel_placement()
                event.accept()
                return
            if event.button() == Qt.LeftButton:
                scene_pos = self.mapToScene(event.position().toPoint())
                obj = scene.place_active_at(scene_pos)
                if obj is not None:
                    obj.setSelected(True)
                keep_active = bool(event.modifiers() & Qt.ShiftModifier)
                if not keep_active:
                    if hasattr(window, "cancel_active_placement"):
                        window.cancel_active_placement()
                    else:
                        scene.cancel_placement()
                event.accept()
                return
        # Pan with Middle mouse or Shift + Left
        item_under_cursor = None
        if event.button() == Qt.LeftButton:
            item_under_cursor = self._map_item_from_graphics_item(
                self.itemAt(event.position().toPoint())
            )
        if (
            event.button() == Qt.LeftButton
            and (event.modifiers() & Qt.ShiftModifier)
            and scene.active_spec is None
            and item_under_cursor is not None
        ):
            item_under_cursor.setSelected(True)
            event.accept()
            return
        if event.button() == Qt.LeftButton and scene.active_spec is None and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            if item_under_cursor is None:
                self.setDragMode(QGraphicsView.RubberBandDrag)
                self._rubber_selecting = True
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton
            and (event.modifiers() & Qt.ShiftModifier)
            and (item_under_cursor is None or scene.active_spec is not None)
        ):
            self._panning = True
            p = event.position()
            self._pan_start = QPointF(p.x(), p.y())
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene: MapScene = self.scene()
        if scene.zone_draw_mode:
            p = event.position()
            scene_pos = self.mapToScene(int(p.x()), int(p.y()))
            scene.update_zone_hover(scene_pos)
            if scene.is_drawing_zone():
                scene.update_zone_draw(scene_pos)
            event.accept()
            return
        if self._panning:
            p = event.position()
            delta = QPointF(p.x(), p.y()) - self._pan_start
            self._pan_start = QPointF(p.x(), p.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        # Update preview position when moving mouse
        p = event.position()
        scene.update_preview(self.mapToScene(int(p.x()), int(p.y())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        scene: MapScene = self.scene()
        if scene.zone_draw_mode and event.button() == Qt.LeftButton:
            zone = scene.finish_zone_draw(self.mapToScene(event.position().toPoint()))
            if zone is not None:
                zone.setSelected(True)
            event.accept()
            return
        if self._panning and (event.button() == Qt.MiddleButton or event.button() == Qt.LeftButton):
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._rubber_selecting and event.button() == Qt.LeftButton:
            self.setDragMode(QGraphicsView.NoDrag)
            self._rubber_selecting = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            scene: MapScene = self.scene()
            to_remove: set[QGraphicsItemGroup] = set()
            for item in scene.selectedItems():
                map_obj = self._map_item_from_graphics_item(item)
                if map_obj is not None:
                    to_remove.add(map_obj)
            if to_remove:
                for obj in to_remove:
                    scene.remove_map_item(obj)
                event.accept()
                return
        super().keyPressEvent(event)


# ----------------------------- Sidebar --------------------------------
class PaletteList(QListWidget):
    def __init__(self, specs: list[ObjectSpec], parent=None):
        super().__init__(parent)
        self.specs = specs
        self.setAlternatingRowColors(True)
        self.populate()
        self.itemClicked.connect(self._on_item_clicked)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    def populate(self):
        self.clear()
        for spec in self.specs:
            item = QListWidgetItem(self._item_label(spec))
            item.setData(Qt.UserRole, spec)
            item.setIcon(create_color_icon(spec.fill))
            self.addItem(item)

    def _item_label(self, spec: ObjectSpec) -> str:
        label = f"{spec.name}  ({spec.size_w}x{spec.size_h})"
        if spec.limit is not None:
            label += f"  [max {spec.limit}]"
        return label

    def _refresh_item_display(self, item: QListWidgetItem, spec: ObjectSpec) -> None:
        item.setText(self._item_label(spec))
        item.setIcon(create_color_icon(spec.fill))

    def _on_item_clicked(self, item: QListWidgetItem):
        spec: ObjectSpec = item.data(Qt.UserRole)
        w = self.window()
        if isinstance(w, MainWindow):
            w.activate_placement(spec)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        spec: ObjectSpec = item.data(Qt.UserRole)
        # Edit default text
        new_name, ok = QInputDialog.getText(self, "Edit default name", "Name:", text=spec.name)
        if ok and new_name.strip():
            spec.name = new_name.strip()
        # Edit color
        color = QColorDialog.getColor(spec.fill, self, "Choose color")
        if color.isValid():
            spec.fill = QColor(color)
        # Edit size
        width, ok_w = QInputDialog.getInt(
            self,
            "Width",
            "Width (cells):",
            value=spec.size_w,
            min=1,
            max=GRID_CELLS,
        )
        height, ok_h = (spec.size_h, False)
        if ok_w:
            height, ok_h = QInputDialog.getInt(
                self,
                "Height",
                "Height (cells):",
                value=spec.size_h,
                min=1,
                max=GRID_CELLS,
            )
        if ok_w and ok_h:
            spec.size_w = width
            spec.size_h = height
        # Update list label/icon
        self._refresh_item_display(item, spec)
        # If this spec is active, refresh preview
        w = self.window()
        if isinstance(w, MainWindow):
            w.refresh_active_preview_if(spec)


class ZoneList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.itemClicked.connect(self._on_item_clicked)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    def _zone_label(self, zone: MapZone) -> str:
        return f"{zone.spec.name}  ({zone.spec.size_w}x{zone.spec.size_h})"

    def _zone_icon(self, zone: MapZone) -> QIcon:
        return create_zone_icon(zone.spec.fill, zone.spec.edge)

    def _refresh_item(self, item: QListWidgetItem, zone: MapZone):
        item.setText(self._zone_label(zone))
        item.setIcon(self._zone_icon(zone))

    def add_zone(self, zone: MapZone):
        item = QListWidgetItem(self._zone_label(zone))
        item.setData(Qt.UserRole, zone)
        item.setIcon(self._zone_icon(zone))
        self.addItem(item)

    def remove_zone(self, zone: MapZone):
        for i in range(self.count()):
            item = self.item(i)
            if item is None:
                continue
            if item.data(Qt.UserRole) is zone:
                self.takeItem(i)
                break

    def update_zone_item(self, zone: MapZone):
        for i in range(self.count()):
            item = self.item(i)
            if item is None:
                continue
            if item.data(Qt.UserRole) is zone:
                self._refresh_item(item, zone)
                break

    def _on_item_clicked(self, item: QListWidgetItem):
        zone: Optional[MapZone] = item.data(Qt.UserRole)
        if zone is None:
            return
        scene = zone.scene()
        if isinstance(scene, MapScene):
            scene.clearSelection()
            zone.setSelected(True)
            for view in scene.views():
                view.centerOn(zone)
                break

    def _on_item_double_clicked(self, item: QListWidgetItem):
        zone: Optional[MapZone] = item.data(Qt.UserRole)
        if zone is None:
            return
        new_name, ok = QInputDialog.getText(self, "Rename zone", "Name:", text=zone.spec.name)
        if ok and new_name.strip():
            zone.spec.name = new_name.strip()
            zone.label_item.setText(zone.spec.name)
            zone.updateLabelLayout()
            scene = zone.scene()
            if isinstance(scene, MapScene):
                scene.zone_updated.emit(zone)
        self.update_zone_item(zone)


class AllianceMembersTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.member_list = QListWidget(self)
        self.member_list.itemDoubleClicked.connect(self._rename_member)
        layout.addWidget(self.member_list)

        controls = QHBoxLayout()
        add_btn = QPushButton("Add Member", self)
        remove_btn = QPushButton("Remove Selected", self)
        controls.addWidget(add_btn)
        controls.addWidget(remove_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        add_btn.clicked.connect(self._add_member)
        remove_btn.clicked.connect(self._remove_selected)

    def _add_member(self):
        name, ok = QInputDialog.getText(self, "Add Member", "Member name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        self.member_list.addItem(name)

    def _remove_selected(self):
        for item in self.member_list.selectedItems():
            self.member_list.takeItem(self.member_list.row(item))

    def _rename_member(self, item: QListWidgetItem):
        current = item.text()
        name, ok = QInputDialog.getText(self, "Rename Member", "Member name:", text=current)
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        item.setText(name)


class AllianceRolesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.role_list = QListWidget(self)
        self.role_list.itemDoubleClicked.connect(self._assign_member)
        layout.addWidget(self.role_list)

        controls = QHBoxLayout()
        add_btn = QPushButton("Add Role", self)
        rename_btn = QPushButton("Rename Role", self)
        remove_btn = QPushButton("Remove Selected", self)
        assign_btn = QPushButton("Assign Member", self)
        controls.addWidget(add_btn)
        controls.addWidget(rename_btn)
        controls.addWidget(assign_btn)
        controls.addWidget(remove_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        add_btn.clicked.connect(self._prompt_add_role)
        rename_btn.clicked.connect(self._rename_role)
        remove_btn.clicked.connect(self._remove_selected)
        assign_btn.clicked.connect(self._prompt_assign_member)

        for role in ["Warlord", "Recruiter", "Muse", "Butler"]:
            self._add_role(role)

    def _role_data(self, role: str, member: Optional[str] = None) -> dict:
        return {"role": role, "member": member}

    def _update_item_text(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        role = data.get("role", "Role")
        member = data.get("member")
        if member:
            item.setText(f"{role} — {member}")
        else:
            item.setText(f"{role} (vacant)")

    def _add_role(self, role: str, member: Optional[str] = None):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, self._role_data(role, member))
        self._update_item_text(item)
        self.role_list.addItem(item)

    def _prompt_add_role(self):
        role, ok = QInputDialog.getText(self, "Add Role", "Role title:")
        if not ok:
            return
        role = role.strip()
        if not role:
            return
        self._add_role(role)

    def _selected_role_item(self) -> Optional[QListWidgetItem]:
        return self.role_list.currentItem()

    def _rename_role(self):
        item = self._selected_role_item()
        if item is None:
            return
        data = item.data(Qt.UserRole) or {}
        role = data.get("role", item.text())
        new_role, ok = QInputDialog.getText(self, "Rename Role", "Role title:", text=role)
        if not ok:
            return
        new_role = new_role.strip()
        if not new_role:
            return
        data["role"] = new_role
        item.setData(Qt.UserRole, data)
        self._update_item_text(item)

    def _remove_selected(self):
        for item in self.role_list.selectedItems():
            self.role_list.takeItem(self.role_list.row(item))

    def _assign_member(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        role = data.get("role", item.text())
        member, ok = QInputDialog.getText(
            self,
            "Assign Member",
            f"Assign member to {role} (leave blank for vacant):",
            text=data.get("member") or "",
        )
        if not ok:
            return
        member = member.strip()
        data["member"] = member or None
        item.setData(Qt.UserRole, data)
        self._update_item_text(item)

    def _prompt_assign_member(self):
        item = self._selected_role_item()
        if item is None:
            return
        self._assign_member(item)


class AllianceWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.members_tab = AllianceMembersTab(self)
        self.roles_tab = AllianceRolesTab(self)
        self.addTab(self.members_tab, "Members")
        self.addTab(self.roles_tab, "Roles")


# ---------------------------- Palette Tabs ----------------------------
class PaletteTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)
        self.tabBarDoubleClicked.connect(self._rename_category)

        corner_widget = QWidget(self)
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(2)

        add_object_btn = QToolButton(corner_widget)
        add_object_btn.setText("+Obj")
        add_object_btn.setToolTip("Add object to current tab")
        add_object_btn.clicked.connect(self._prompt_new_object)
        corner_layout.addWidget(add_object_btn)

        add_tab_btn = QToolButton(corner_widget)
        add_tab_btn.setText("+Tab")
        add_tab_btn.setToolTip("Add new category tab")
        add_tab_btn.clicked.connect(self._prompt_new_category)
        corner_layout.addWidget(add_tab_btn)

        self.setCornerWidget(corner_widget, Qt.TopRightCorner)

        for name, specs in DEFAULT_CATEGORIES.items():
            self.add_category(name, specs)

    def add_category(self, name: str, specs: Optional[list[ObjectSpec]] = None):
        if specs is None:
            specs = []
        list_widget = PaletteList(specs, self)
        self.addTab(list_widget, name)
        return list_widget

    def add_object_to_tab(self, tab_index: int, spec: ObjectSpec) -> None:
        if tab_index < 0 or tab_index >= self.count():
            raise IndexError("Tab index out of range")
        widget = self.widget(tab_index)
        if not isinstance(widget, PaletteList):
            raise TypeError("Tab widget is not a PaletteList")
        widget.specs.append(spec)
        widget.populate()
        widget.setCurrentRow(widget.count() - 1)

    def _prompt_new_object(self):
        index = self.currentIndex()
        if index < 0:
            return

        name, ok = QInputDialog.getText(self, "Add Object", "Object name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return

        width, ok_w = QInputDialog.getInt(
            self,
            "Width",
            "Width (cells):",
            value=3,
            min=1,
            max=GRID_CELLS,
        )
        if not ok_w:
            return
        height, ok_h = QInputDialog.getInt(
            self,
            "Height",
            "Height (cells):",
            value=3,
            min=1,
            max=GRID_CELLS,
        )
        if not ok_h:
            return

        color = QColorDialog.getColor(QColor(Qt.lightGray), self, "Choose color")
        if color.isValid():
            fill = QColor(color)
        else:
            fill = QColor(Qt.lightGray)

        spec = ObjectSpec(name, width, height, fill)
        self.add_object_to_tab(index, spec)

    def _prompt_new_category(self):
        name, ok = QInputDialog.getText(self, "Add Category", "Category name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if self._category_exists(name):
            QMessageBox.information(self, "Category exists", f"Category '{name}' already exists.")
            return
        self.add_category(name)

    def _rename_category(self, index: int):
        if index < 0:
            return
        current_name = self.tabText(index)
        name, ok = QInputDialog.getText(self, "Rename Category", "Category name:", text=current_name)
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if name != current_name and self._category_exists(name):
            QMessageBox.information(self, "Category exists", f"Category '{name}' already exists.")
            return
        self.setTabText(index, name)

    def _category_exists(self, name: str) -> bool:
        for i in range(self.count()):
            if self.tabText(i).lower() == name.lower():
                return True
        return False


# ----------------------------- Main Window -----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Last War Survivor — Alliance Map Tool")
        self.resize(1200, 800)

        # Scene & View
        self.scene = MapScene(GRID_CELLS, CELL_SIZE, self)
        self.view = MapView(self.scene, self)
        self.setCentralWidget(self.view)

        # Sidebar (dock)
        self.palette_tabs = PaletteTabWidget(self)
        self.object_dock = QDockWidget("Objects", self)
        self.object_dock.setWidget(self.palette_tabs)
        self.object_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.object_dock)

        self.zone_list = ZoneList(self)
        self.zone_dock = QDockWidget("Zones", self)
        self.zone_dock.setWidget(self.zone_list)
        self.zone_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.zone_dock)

        self.alliance_widget = AllianceWidget(self)
        self.alliance_dock = QDockWidget("Alliance", self)
        self.alliance_dock.setWidget(self.alliance_widget)
        self.alliance_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.alliance_dock)

        # Status bar with coordinates + hint
        self.coord_label = QLabel("x: -, y: -")
        self.hint_label = QLabel("")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().addPermanentWidget(self.hint_label)
        self.view.setMouseTracking(True)
        self.view.viewport().installEventFilter(self)

        # Toolbar actions
        toolbar = QToolBar("Tools", self)
        self.addToolBar(toolbar)

        self.act_toggle_grid = QAction("Toggle Grid", self)
        self.act_toggle_grid.setCheckable(True)
        self.act_toggle_grid.setChecked(True)
        self.act_toggle_grid.triggered.connect(self.toggle_grid)
        toolbar.addAction(self.act_toggle_grid)

        toolbar.addSeparator()
        self.act_draw_zone = QAction("Draw Zone", self)
        self.act_draw_zone.setCheckable(True)
        self.act_draw_zone.triggered.connect(self._on_zone_draw_toggled)
        toolbar.addAction(self.act_draw_zone)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Cell size:"))
        self.spin_cell = QSpinBox()
        self.spin_cell.setRange(5, 120)
        self.spin_cell.setValue(CELL_SIZE)
        self.spin_cell.valueChanged.connect(self.change_cell_size)
        toolbar.addWidget(self.spin_cell)

        self.panel_toolbar = QToolBar("Panels", self)
        self.addToolBar(self.panel_toolbar)
        obj_action = self.object_dock.toggleViewAction()
        obj_action.setText("Objects Panel")
        zone_action = self.zone_dock.toggleViewAction()
        zone_action.setText("Zones Panel")
        alliance_action = self.alliance_dock.toggleViewAction()
        alliance_action.setText("Alliance Panel")
        self.panel_toolbar.addAction(obj_action)
        self.panel_toolbar.addAction(zone_action)
        self.panel_toolbar.addAction(alliance_action)

        self.scene.zone_created.connect(self.zone_list.add_zone)
        self.scene.zone_updated.connect(self.zone_list.update_zone_item)
        self.scene.zone_removed.connect(self.zone_list.remove_zone)
        self.scene.zone_redraw_finished.connect(self._on_zone_redraw_finished)

    def activate_placement(self, spec: ObjectSpec):
        self.set_zone_draw_mode(False)
        self.scene.set_active_spec(spec)
        self.hint_label.setText(
            f"Placing {spec.name}: Left-click to place, Shift+Click for multiple, Right-click to cancel"
        )

    def set_zone_draw_mode(self, enabled: bool):
        if enabled:
            if self.scene.active_spec is not None:
                self.scene.cancel_placement()
        self.scene.set_zone_draw_mode(enabled)
        if enabled:
            views = self.scene.views()
            if views:
                view = views[0]
                cursor_pos = view.mapFromGlobal(QCursor.pos())
                if view.rect().contains(cursor_pos):
                    scene_pos = view.mapToScene(cursor_pos)
                    self.scene.update_zone_hover(scene_pos)
        previous = self.act_draw_zone.blockSignals(True)
        self.act_draw_zone.setChecked(enabled)
        self.act_draw_zone.blockSignals(previous)
        if enabled:
            self.hint_label.setText(
                "Draw zone: Click and drag to create a zone. Right-click to cancel or exit the tool"
            )
        elif self.scene.active_spec is None:
            self.clear_placement_hint()

    def begin_zone_redraw(self, zone: MapZone):
        if not self.scene.zone_draw_mode:
            self.set_zone_draw_mode(True)
        self.scene.prepare_zone_redraw(zone)
        zone.setSelected(True)
        for view in self.scene.views():
            view.centerOn(zone)
            break
        self.hint_label.setText(
            "Redraw zone: Click and drag to define the new area. Right-click to cancel."
        )

    def _on_zone_redraw_finished(self, zone: MapZone):
        self.set_zone_draw_mode(False)
        zone.setSelected(True)

    def _on_zone_draw_toggled(self, checked: bool):
        self.set_zone_draw_mode(checked)

    def refresh_active_preview_if(self, spec: ObjectSpec):
        if self.scene.active_spec is spec:
            self.scene.set_active_spec(spec)

    def clear_placement_hint(self):
        self.hint_label.setText("")

    def cancel_active_placement(self):
        any_cancelled = False
        if self.scene.active_spec is not None:
            self.scene.cancel_placement()
            any_cancelled = True
        if self.scene.zone_draw_mode:
            self.set_zone_draw_mode(False)
            any_cancelled = True
        if any_cancelled:
            self.clear_placement_hint()

    def toggle_grid(self, checked: bool):
        self.scene.show_grid = checked
        if hasattr(self.scene, "grid_item"):
            self.scene.grid_item.setVisible(checked)
            self.scene.grid_item.update()
        self.scene.update()

    def change_cell_size(self, v: int):
        # Rescale scene: update cell size, scene rect, and items
        self.scene.cell_size = v
        size_px = self.scene.cells * v
        self.scene.setSceneRect(0, 0, size_px, size_px)
        if hasattr(self.scene, "grid_item"):
            self.scene.grid_item.update_geometry()
            self.scene.grid_item.update()
        # Update existing items
        for item in self.scene.items():
            if isinstance(item, MapObject):
                item.cell_size = v
                w = item.spec.size_w * v
                h = item.spec.size_h * v
                item.rect_item.setRect(0, 0, w, h)
                item.updateLabelLayout()
                top_left = item.pos()
                snapped_x = round(top_left.x() / v) * v
                snapped_y = round(top_left.y() / v) * v
                clamped = self.scene._clamp_top_left(snapped_x, snapped_y, w, h)
                item.setPos(clamped)
            elif isinstance(item, MapZone):
                item.cell_size = v
                w = item.spec.size_w * v
                h = item.spec.size_h * v
                item.rect_item.setRect(0, 0, w, h)
                item.updateLabelLayout()
                top_left = item.pos()
                snapped_x = round(top_left.x() / v) * v
                snapped_y = round(top_left.y() / v) * v
                clamped = self.scene._clamp_top_left(snapped_x, snapped_y, w, h)
                item.setPos(clamped)
            elif isinstance(item, PreviewObject):
                item.update_for_cell_size(v)
        self.scene.update()
        self.scene.update_zone_draw_visuals()

    def eventFilter(self, watched, event):
        # Show bottom-left-origin coordinates under cursor and drive preview visibility/position
        if watched is self.view.viewport():
            if event.type() == QEvent.MouseMove:
                p = event.position()
                scene_pos = self.view.mapToScene(int(p.x()), int(p.y()))
                cs = self.scene.cell_size
                cells = self.scene.cells
                x_raw = max(0.0, min(self.scene.scene_width(), float(scene_pos.x())))
                y_raw = max(0.0, min(self.scene.scene_height(), float(scene_pos.y())))
                # 1-based X, bottom-left-origin Y (invert Y)
                cx = int(x_raw // cs) + 1
                cy = int((self.scene.scene_height() - y_raw) // cs) + 1
                cx = max(1, min(cells, cx))
                cy = max(1, min(cells, cy))
                self.coord_label.setText(f"x: {cx}, y: {cy}")
                self.scene.update_preview(scene_pos)
                self.scene.update_zone_hover(scene_pos)
            elif event.type() == QEvent.Leave:
                if self.scene.preview_item is not None:
                    self.scene.preview_item.setVisible(False)
                if self.scene.zone_draw_mode:
                    self.scene.hide_zone_hover()
            elif event.type() == QEvent.Enter:
                if self.scene.preview_item is not None:
                    self.scene.preview_item.setVisible(True)
                if self.scene.zone_draw_mode:
                    self.scene.show_zone_hover()
        return super().eventFilter(watched, event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
