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
import uuid
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Dict, Iterable, List, Optional, Set

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
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QInputDialog,
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
    template_id: str = field(default_factory=lambda: uuid.uuid4().hex)

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


RANK_ORDER = ["R1", "R2", "R3", "R4", "R5"]
RANK_COLORS: Dict[str, QColor] = {
    "R1": QColor("#b0bec5"),
    "R2": QColor("#90caf9"),
    "R3": QColor("#a5d6a7"),
    "R4": QColor("#ffe082"),
    "R5": QColor("#f48fb1"),
}


@dataclass
class MemberData:
    name: str
    member_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    rank: str = "R1"
    roles: List[str] = field(default_factory=list)
    map_object: Optional["MapObject"] = None
    template_id: str = field(init=False)

    _palette_lookup: ClassVar[Optional[Callable[[str], Optional[QColor]]]] = None
    _rank_color_cache: ClassVar[Dict[str, QColor]] = {}

    def __post_init__(self):
        self.template_id = f"member:{self.member_id}"

    def display_text(self) -> str:
        roles_text = ", ".join(self.roles)
        if roles_text:
            return f"{self.rank} {self.name} — {roles_text}"
        return f"{self.rank} {self.name}"

    def rank_color(self) -> QColor:
        cls = self.__class__
        cached = cls._rank_color_cache.get(self.rank)
        if cached is not None:
            return QColor(cached)

        lookup = cls._palette_lookup
        if lookup is not None:
            palette_color = lookup(self.rank)
            if palette_color is not None and palette_color.isValid():
                color_copy = QColor(palette_color)
                cls._rank_color_cache[self.rank] = QColor(color_copy)
                return color_copy

        color = RANK_COLORS.get(self.rank)
        return QColor(color) if color is not None else QColor(Qt.lightGray)

    def placement_spec(self) -> ObjectSpec:
        color = self.rank_color()
        return ObjectSpec(
            name=self.name,
            size_w=3,
            size_h=3,
            fill=color,
            limit=1,
            limit_key=self.template_id,
            template_id=self.template_id,
        )

    @classmethod
    def set_palette_lookup(
        cls, lookup: Optional[Callable[[str], Optional[QColor]]]
    ) -> None:
        cls._palette_lookup = lookup
        cls._rank_color_cache.clear()

    @classmethod
    def update_rank_color_cache(cls, rank: str, color: Optional[QColor]) -> None:
        if color is None:
            cls._rank_color_cache.pop(rank, None)
        else:
            cls._rank_color_cache[rank] = QColor(color)

    @classmethod
    def clear_rank_color_cache(cls) -> None:
        cls._rank_color_cache.clear()


@dataclass
class RoleRecord:
    name: str
    role_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    member_id: Optional[str] = None
    allowed_ranks: Optional[Set[str]] = None
    standard: bool = False

    def allows_rank(self, rank: str) -> bool:
        if self.allowed_ranks is None:
            return True
        return rank in self.allowed_ranks

DEFAULT_CATEGORIES: dict[str, list[ObjectSpec]] = {
    "Alliance": [
        ObjectSpec("R1", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("R2", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("R3", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("R4", 3, 3, QColor(Qt.lightGray), limit=10, limit_key="R4"),
        ObjectSpec("R5", 3, 3, QColor(Qt.lightGray), limit=1, limit_key="R5"),
        ObjectSpec("Base", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("MG", 3, 3, QColor(Qt.lightGray), limit=1, limit_key="MG"),
        ObjectSpec("Furnace", 4, 4, QColor(Qt.lightGray), limit=1, limit_key="Furnace"),
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
        spec.template_id,
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
        if not color.isValid():
            return False

        new_fill = QColor(color)
        if new_fill == self.spec.fill:
            return False

        self.spec.fill = new_fill
        self.rect_item.setBrush(QBrush(self.spec.fill))

        scene = self.scene()
        if scene is not None:
            main_window = None
            for view in scene.views():
                window = view.window()
                if isinstance(window, MainWindow):
                    main_window = window
                    break
            if main_window is not None:
                template_id = getattr(self.spec, "template_id", "")
                if template_id:
                    palette_spec = main_window.palette_tabs.update_spec_fill(
                        template_id, self.spec.fill
                    )
                    if (
                        palette_spec is not None
                        and scene.active_spec is not None
                        and getattr(scene.active_spec, "template_id", None) == template_id
                    ):
                        main_window.refresh_active_preview_if(scene.active_spec)
        return True

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
    object_placed = Signal(object)
    object_removed = Signal(object)

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
        self.object_placed.emit(obj)
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
        if isinstance(item, MapObject):
            self.object_removed.emit(item)
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
            key_display = spec.limit_key or spec.name
            label += f"  [max {spec.limit} — {key_display}]"
        return label

    def find_spec_by_name(self, name: str) -> Optional[ObjectSpec]:
        for spec in self.specs:
            if spec.name == name:
                return spec
        return None

    def find_spec_by_template(self, template_id: str) -> Optional[ObjectSpec]:
        for spec in self.specs:
            if spec.template_id == template_id:
                return spec
        return None

    def _item_for_spec(self, spec: ObjectSpec) -> Optional[QListWidgetItem]:
        for i in range(self.count()):
            item = self.item(i)
            if item is None:
                continue
            if item.data(Qt.UserRole) is spec:
                return item
        return None

    def _refresh_item_display(self, item: QListWidgetItem, spec: ObjectSpec) -> None:
        item.setText(self._item_label(spec))
        item.setIcon(create_color_icon(spec.fill))

    def refresh_spec_item(self, spec: ObjectSpec) -> None:
        item = self._item_for_spec(spec)
        if item is not None:
            self._refresh_item_display(item, spec)

    def _on_item_clicked(self, item: QListWidgetItem):
        spec: ObjectSpec = item.data(Qt.UserRole)
        w = self.window()
        if isinstance(w, MainWindow):
            w.activate_placement(spec)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        spec: ObjectSpec = item.data(Qt.UserRole)
        previous = {
            "name": spec.name,
            "fill": QColor(spec.fill),
            "size_w": spec.size_w,
            "size_h": spec.size_h,
            "limit": spec.limit,
            "limit_key": spec.limit_key,
        }
        changed = False
        # Edit default text
        new_name, ok = QInputDialog.getText(self, "Edit default name", "Name:", text=spec.name)
        if ok and new_name.strip():
            final_name = new_name.strip()
            if final_name != spec.name:
                spec.name = final_name
                changed = True
        # Edit color
        color = QColorDialog.getColor(spec.fill, self, "Choose color")
        if color.isValid():
            if color != spec.fill:
                spec.fill = QColor(color)
                changed = True
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
            if spec.size_w != width or spec.size_h != height:
                spec.size_w = width
                spec.size_h = height
                changed = True
        # Edit limit
        limit_prompt_text = "" if spec.limit is None else str(spec.limit)
        new_limit = spec.limit
        new_limit_key = spec.limit_key or spec.name
        limit_confirmed = False
        while True:
            limit_text, ok_limit = QInputDialog.getText(
                self,
                "Placement limit",
                "Maximum placements (leave blank for unlimited):",
                text=limit_prompt_text,
            )
            if not ok_limit:
                break
            limit_text = limit_text.strip()
            if not limit_text:
                new_limit = None
                new_limit_key = spec.name
                limit_confirmed = True
                break
            try:
                parsed_limit = int(limit_text)
            except ValueError:
                QMessageBox.information(
                    self,
                    "Invalid limit",
                    "Enter a whole number greater than zero or leave blank for no limit.",
                )
                continue
            if parsed_limit <= 0:
                QMessageBox.information(
                    self,
                    "Invalid limit",
                    "Limit must be greater than zero or left blank to remove the cap.",
                )
                continue
            new_limit = parsed_limit
            limit_confirmed = True
            break

        if limit_confirmed and new_limit is not None:
            key_prompt_text = spec.limit_key or spec.name
            while True:
                key_text, ok_key = QInputDialog.getText(
                    self,
                    "Shared limit key",
                    "Objects sharing this key count toward the same limit:",
                    text=key_prompt_text,
                )
                if not ok_key:
                    limit_confirmed = False
                    break
                key_text = key_text.strip()
                if not key_text:
                    QMessageBox.information(
                        self,
                        "Invalid key",
                        "Limit key cannot be blank when a limit is set.",
                    )
                    continue
                new_limit_key = key_text
                break

        if limit_confirmed:
            if spec.limit != new_limit:
                spec.limit = new_limit
                changed = True
            if spec.limit_key != new_limit_key:
                spec.limit_key = new_limit_key
                changed = True
        # Update list label/icon
        self._refresh_item_display(item, spec)
        # If this spec is active, refresh preview
        w = self.window()
        if isinstance(w, MainWindow):
            if changed:
                w.offer_apply_spec_changes(spec, previous)
            w.refresh_active_preview_if(spec)
        if changed:
            self._notify_spec_changed(spec, previous)

    def _notify_spec_changed(self, spec: ObjectSpec, previous: dict) -> None:
        parent = self.parent()
        while parent is not None and not isinstance(parent, PaletteTabWidget):
            parent = parent.parent()
        if isinstance(parent, PaletteTabWidget):
            parent.handle_spec_changed(spec, previous)


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
        self.roles_tab: Optional["AllianceRolesTab"] = None
        self.members: List[MemberData] = []
        self._selected_member_id: Optional[str] = None
        self._deferred_select_id: Optional[str] = None
        self._deferred_activate = False
        self._palette_widget: Optional["PaletteTabWidget"] = None

        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter by rank:"))
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItem("All")
        for rank in RANK_ORDER:
            self.filter_combo.addItem(rank)
        filter_row.addWidget(self.filter_combo)
        self.sort_checkbox = QCheckBox("Sort by rank", self)
        filter_row.addWidget(self.sort_checkbox)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.member_list = QListWidget(self)
        self.member_list.setAlternatingRowColors(True)
        self.member_list.itemDoubleClicked.connect(self._rename_member)
        self.member_list.itemClicked.connect(self._on_member_clicked)
        self.member_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.member_list.customContextMenuRequested.connect(self._show_context_menu)
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
        self.filter_combo.currentIndexChanged.connect(self._refresh_list)
        self.sort_checkbox.stateChanged.connect(self._refresh_list)

        self._refresh_list()

    def set_palette_widget(self, palette: Optional["PaletteTabWidget"]):
        if self._palette_widget is palette:
            return
        if self._palette_widget is not None:
            try:
                self._palette_widget.rank_spec_changed.disconnect(
                    self._on_rank_spec_changed
                )
            except TypeError:
                pass
        self._palette_widget = palette
        if self._palette_widget is not None:
            self._palette_widget.rank_spec_changed.connect(self._on_rank_spec_changed)

    def _refresh_list(self, *args):
        select_id = self._deferred_select_id
        activate = self._deferred_activate
        self._deferred_select_id = None
        self._deferred_activate = False
        previous_selected = select_id or self._selected_member_id
        filter_rank = self.filter_combo.currentText() if self.filter_combo.count() else "All"
        if filter_rank != "All":
            filtered = [member for member in self.members if member.rank == filter_rank]
        else:
            filtered = list(self.members)
        if self.sort_checkbox.isChecked():
            filtered.sort(key=lambda m: (RANK_ORDER.index(m.rank), m.name.lower()))
        self.member_list.blockSignals(True)
        self.member_list.clear()
        selected_item: Optional[QListWidgetItem] = None
        for member in filtered:
            item = QListWidgetItem(member.display_text())
            item.setData(Qt.UserRole, member.member_id)
            self.member_list.addItem(item)
            if previous_selected and member.member_id == previous_selected:
                selected_item = item
        if selected_item is not None:
            self.member_list.setCurrentItem(selected_item)
            self._selected_member_id = selected_item.data(Qt.UserRole)
        elif self.member_list.count() > 0:
            self.member_list.setCurrentRow(0)
            current_item = self.member_list.currentItem()
            self._selected_member_id = (
                current_item.data(Qt.UserRole) if current_item is not None else None
            )
        else:
            self._selected_member_id = None
        self.member_list.blockSignals(False)
        if activate and self._selected_member_id is not None:
            self._activate_member_by_id(self._selected_member_id)

    def _activate_member_by_id(self, member_id: Optional[str]):
        if member_id is None:
            return
        member = self.get_member(member_id)
        if member is None:
            return
        window = self.window()
        if isinstance(window, MainWindow):
            window.activate_member(member)

    def _add_member(self):
        name, ok = QInputDialog.getText(self, "Add Member", "Member name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        member = MemberData(name=name)
        self.members.append(member)
        self._deferred_select_id = member.member_id
        self._deferred_activate = True
        self._refresh_list()

    def _remove_member_by_id(self, member_id: str):
        member = self.get_member(member_id)
        if member is None:
            return
        window = self.window()
        if isinstance(window, MainWindow):
            if getattr(window, "active_member", None) is member:
                window.cancel_active_placement()
            if member.map_object is not None:
                window.scene.remove_map_item(member.map_object)
        if self.roles_tab is not None:
            self.roles_tab.handle_member_removed(member.member_id)
        self.members = [m for m in self.members if m.member_id != member.member_id]

    def _remove_selected(self):
        selected_ids = [item.data(Qt.UserRole) for item in self.member_list.selectedItems()]
        for member_id in selected_ids:
            if member_id:
                self._remove_member_by_id(member_id)
        self._refresh_list()

    def _member_from_item(self, item: Optional[QListWidgetItem]) -> Optional[MemberData]:
        if item is None:
            return None
        member_id = item.data(Qt.UserRole)
        return self.get_member(member_id) if member_id else None

    def _rename_member(self, item: QListWidgetItem):
        member = self._member_from_item(item)
        if member is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Member", "Member name:", text=member.name)
        if not ok:
            return
        name = name.strip()
        if not name or name == member.name:
            return
        member.name = name
        self._update_member_map_object(member)
        if self.roles_tab is not None:
            self.roles_tab.handle_member_renamed(member.member_id, member.name)
        window = self.window()
        if isinstance(window, MainWindow) and getattr(window, "active_member", None) is member:
            self._deferred_activate = True
        else:
            self._deferred_activate = False
        self._deferred_select_id = member.member_id
        self._refresh_list()

    def _on_member_clicked(self, item: QListWidgetItem):
        member = self._member_from_item(item)
        if member is None:
            return
        self._selected_member_id = member.member_id
        self._activate_member_by_id(member.member_id)

    def _show_context_menu(self, point):
        item = self.member_list.itemAt(point)
        member = self._member_from_item(item)
        if member is None:
            return
        menu = QMenu(self)
        actions = []
        for rank in RANK_ORDER:
            action = menu.addAction(rank)
            action.setData(rank)
            action.setCheckable(True)
            action.setChecked(rank == member.rank)
            actions.append(action)
        chosen = menu.exec(self.member_list.mapToGlobal(point))
        if chosen is None:
            return
        rank = chosen.data()
        if rank:
            self._set_member_rank(member, rank)

    def _count_rank(self, rank: str) -> int:
        return sum(1 for member in self.members if member.rank == rank)

    def _set_member_rank(self, member: MemberData, rank: str):
        if member.rank == rank:
            return
        if rank == "R5":
            count = self._count_rank("R5")
            if member.rank == "R5":
                count -= 1
            if count >= 1:
                QMessageBox.information(self, "Rank limit", "Only one member may hold rank R5 at a time.")
                return
        if rank == "R4":
            count = self._count_rank("R4")
            if member.rank == "R4":
                count -= 1
            if count >= 10:
                QMessageBox.information(self, "Rank limit", "Only ten members may hold rank R4 at a time.")
                return
        member.rank = rank
        self._update_member_map_object(member)
        window = self.window()
        if isinstance(window, MainWindow) and getattr(window, "active_member", None) is member:
            self._deferred_activate = True
        else:
            self._deferred_activate = False
        if self.roles_tab is not None:
            self.roles_tab.handle_member_rank_changed(member.member_id, rank)
        self._deferred_select_id = member.member_id
        self._refresh_list()

    def _update_member_map_object(self, member: MemberData):
        if member.map_object is None:
            return
        color = member.rank_color()
        obj = member.map_object
        obj.spec.name = member.name
        obj.label_item.setText(member.name)
        obj.updateLabelLayout()
        obj.spec.fill = QColor(color)
        obj.rect_item.setBrush(QBrush(obj.spec.fill))
        obj._last_valid_pos = QPointF(obj.pos())

    def _on_rank_spec_changed(self, rank: str):
        for member in self.members:
            if member.rank == rank:
                self._update_member_map_object(member)
        window = self.window()
        if isinstance(window, MainWindow):
            active_member = getattr(window, "active_member", None)
            if isinstance(active_member, MemberData) and active_member.rank == rank:
                window.activate_member(active_member)

    def get_member(self, member_id: Optional[str]) -> Optional[MemberData]:
        if member_id is None:
            return None
        for member in self.members:
            if member.member_id == member_id:
                return member
        return None

    def find_member_by_template(self, template_id: str) -> Optional[MemberData]:
        for member in self.members:
            if member.template_id == template_id:
                return member
        return None

    def handle_member_object_placed(self, template_id: str, obj: MapObject):
        member = self.find_member_by_template(template_id)
        if member is None:
            return
        member.map_object = obj
        self._update_member_map_object(member)

    def handle_member_object_removed(self, template_id: str):
        member = self.find_member_by_template(template_id)
        if member is None:
            return
        member.map_object = None

    def assign_role(self, member_id: str, role_name: str):
        member = self.get_member(member_id)
        if member is None:
            return
        if role_name not in member.roles:
            member.roles.append(role_name)
            member.roles.sort(key=str.lower)
            self._deferred_select_id = member.member_id
            self._deferred_activate = False
            self._refresh_list()

    def unassign_role(self, member_id: str, role_name: str):
        member = self.get_member(member_id)
        if member is None:
            return
        if role_name in member.roles:
            member.roles = [r for r in member.roles if r != role_name]
            self._deferred_select_id = member.member_id
            self._deferred_activate = False
            self._refresh_list()

    def rename_role(self, old_name: str, new_name: str):
        changed = False
        for member in self.members:
            if old_name in member.roles:
                member.roles = [new_name if r == old_name else r for r in member.roles]
                member.roles.sort(key=str.lower)
                changed = True
        if changed:
            self._refresh_list()

    def remove_role_name(self, role_name: str):
        changed = False
        for member in self.members:
            if role_name in member.roles:
                member.roles = [r for r in member.roles if r != role_name]
                changed = True
        if changed:
            self._refresh_list()

    def eligible_members(self, allowed_ranks: Optional[Set[str]]) -> List[MemberData]:
        if allowed_ranks is None:
            return list(self.members)
        return [member for member in self.members if member.rank in allowed_ranks]


class RoleConfigDialog(QDialog):
    def __init__(self, parent=None, role_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add Role")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Role title:"))
        self.name_edit = QLineEdit(self)
        self.name_edit.setText(role_name)
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Allow assignment to ranks:"))
        ranks_layout = QHBoxLayout()
        self.rank_checks: Dict[str, QCheckBox] = {}
        for rank in RANK_ORDER:
            cb = QCheckBox(rank, self)
            cb.setChecked(True)
            self.rank_checks[rank] = cb
            ranks_layout.addWidget(cb)
        ranks_layout.addStretch(1)
        layout.addLayout(ranks_layout)
        note = QLabel("Uncheck ranks to restrict who can hold this role.", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def role_name(self) -> str:
        return self.name_edit.text().strip()

    def selected_ranks(self) -> Set[str]:
        return {rank for rank, cb in self.rank_checks.items() if cb.isChecked()}


class RoleAssignmentDialog(QDialog):
    def __init__(
        self,
        role_name: str,
        members: List[MemberData],
        current_member_id: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Assign {role_name}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a member for this role:"))
        self.list_widget = QListWidget(self)
        vacancy_item = QListWidgetItem("Vacant")
        vacancy_item.setData(Qt.UserRole, None)
        self.list_widget.addItem(vacancy_item)
        default_row = 0
        for member in members:
            item = QListWidgetItem(f"{member.rank} {member.name}")
            item.setData(Qt.UserRole, member.member_id)
            self.list_widget.addItem(item)
            if current_member_id and member.member_id == current_member_id:
                default_row = self.list_widget.count() - 1
        self.list_widget.setCurrentRow(default_row)
        self.list_widget.itemDoubleClicked.connect(lambda *_: self.accept())
        layout.addWidget(self.list_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_member_id(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item is not None else None


class AllianceRolesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.members_tab: Optional[AllianceMembersTab] = None
        self.roles: List[RoleRecord] = []
        self._selected_role_id: Optional[str] = None

        layout = QVBoxLayout(self)
        self.role_list = QListWidget(self)
        self.role_list.itemDoubleClicked.connect(self._on_item_double_clicked)
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

        for role_name in ["Warlord", "Recruiter", "Muse", "Butler"]:
            self._add_role_record(
                RoleRecord(role_name, allowed_ranks={"R4"}, standard=True)
            )

    def _on_item_double_clicked(self, item: QListWidgetItem):
        role = self._role_from_item(item)
        if role is not None:
            self._assign_role(role)

    def _role_from_item(self, item: Optional[QListWidgetItem]) -> Optional[RoleRecord]:
        if item is None:
            return None
        role_id = item.data(Qt.UserRole)
        return self.get_role(role_id)

    def get_role(self, role_id: Optional[str]) -> Optional[RoleRecord]:
        if role_id is None:
            return None
        for record in self.roles:
            if record.role_id == role_id:
                return record
        return None

    def _refresh_roles(self, select_id: Optional[str] = None):
        previous = select_id or self._selected_role_id
        self.role_list.blockSignals(True)
        self.role_list.clear()
        selected_item = None
        for record in self.roles:
            item = QListWidgetItem(self._role_text(record))
            item.setData(Qt.UserRole, record.role_id)
            self.role_list.addItem(item)
            if previous and record.role_id == previous:
                selected_item = item
        if selected_item is not None:
            self.role_list.setCurrentItem(selected_item)
            self._selected_role_id = selected_item.data(Qt.UserRole)
        elif self.role_list.count() > 0:
            self.role_list.setCurrentRow(0)
            current_item = self.role_list.currentItem()
            self._selected_role_id = (
                current_item.data(Qt.UserRole) if current_item is not None else None
            )
        else:
            self._selected_role_id = None
        self.role_list.blockSignals(False)

    def _role_text(self, record: RoleRecord) -> str:
        member_name = ""
        if record.member_id and self.members_tab is not None:
            member = self.members_tab.get_member(record.member_id)
            if member is not None:
                member_name = member.name
        if member_name:
            return f"{record.name} — {member_name}"
        return f"{record.name} (vacant)"

    def _add_role_record(self, record: RoleRecord):
        self.roles.append(record)
        self._refresh_roles(select_id=record.role_id)

    def _prompt_add_role(self):
        dialog = RoleConfigDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.role_name()
        if not name:
            return
        selected_ranks = dialog.selected_ranks()
        if not selected_ranks or len(selected_ranks) == len(RANK_ORDER):
            allowed = None
        else:
            allowed = set(selected_ranks)
        record = RoleRecord(name, allowed_ranks=allowed)
        self._add_role_record(record)

    def _current_role(self) -> Optional[RoleRecord]:
        return self.get_role(self._selected_role_id)

    def _rename_role(self):
        record = self._current_role()
        if record is None:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Role", "Role title:", text=record.name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == record.name:
            return
        old_name = record.name
        record.name = new_name
        if self.members_tab is not None:
            self.members_tab.rename_role(old_name, new_name)
        self._refresh_roles(select_id=record.role_id)

    def _remove_selected(self):
        selected_ids = [item.data(Qt.UserRole) for item in self.role_list.selectedItems()]
        updated = False
        for role_id in selected_ids:
            record = self.get_role(role_id)
            if record is None:
                continue
            if record.member_id and self.members_tab is not None:
                self.members_tab.unassign_role(record.member_id, record.name)
            if self.members_tab is not None:
                self.members_tab.remove_role_name(record.name)
            self.roles = [r for r in self.roles if r.role_id != role_id]
            updated = True
        if updated:
            self._refresh_roles()

    def _prompt_assign_member(self):
        record = self._current_role()
        if record is None:
            return
        self._assign_role(record)

    def _assign_role(self, record: RoleRecord):
        if self.members_tab is None:
            return
        eligible = self.members_tab.eligible_members(record.allowed_ranks)
        if not eligible and record.member_id is None:
            QMessageBox.information(
                self,
                "No eligible members",
                "No members meet the rank requirements for this role.",
            )
            return
        dialog = RoleAssignmentDialog(
            record.name,
            eligible,
            current_member_id=record.member_id,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        selected_member_id = dialog.selected_member_id()
        if selected_member_id == record.member_id:
            return
        if record.member_id and self.members_tab is not None:
            self.members_tab.unassign_role(record.member_id, record.name)
        record.member_id = selected_member_id
        if selected_member_id and self.members_tab is not None:
            self.members_tab.assign_role(selected_member_id, record.name)
        self._refresh_roles(select_id=record.role_id)

    def handle_member_removed(self, member_id: str):
        updated = False
        for record in self.roles:
            if record.member_id == member_id:
                record.member_id = None
                updated = True
        if updated:
            self._refresh_roles()

    def handle_member_renamed(self, member_id: str, new_name: str):
        if any(record.member_id == member_id for record in self.roles):
            self._refresh_roles()

    def handle_member_rank_changed(self, member_id: str, new_rank: str):
        if self.members_tab is None:
            return
        removed_roles: List[str] = []
        for record in self.roles:
            if record.member_id == member_id and not record.allows_rank(new_rank):
                if record.member_id and self.members_tab is not None:
                    self.members_tab.unassign_role(record.member_id, record.name)
                record.member_id = None
                removed_roles.append(record.name)
        if removed_roles:
            member = self.members_tab.get_member(member_id)
            if member is not None:
                QMessageBox.information(
                    self,
                    "Role unassigned",
                    f"{member.name} no longer meets the rank requirements for: {', '.join(removed_roles)}.",
                )
            self._refresh_roles()


class AllianceWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.members_tab = AllianceMembersTab(self)
        self.roles_tab = AllianceRolesTab(self)
        self.members_tab.roles_tab = self.roles_tab
        self.roles_tab.members_tab = self.members_tab
        self.roles_tab._refresh_roles()
        self.addTab(self.members_tab, "Members")
        self.addTab(self.roles_tab, "Roles")


# ---------------------------- Palette Tabs ----------------------------
class PaletteTabWidget(QTabWidget):
    rank_spec_changed = Signal(str)

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

    def rank_template_color(self, rank: str) -> Optional[QColor]:
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, PaletteList):
                spec = widget.find_spec_by_name(rank)
                if spec is not None:
                    return QColor(spec.fill)
        return None

    def update_spec_fill(self, template_id: str, color: QColor) -> Optional[ObjectSpec]:
        for i in range(self.count()):
            widget = self.widget(i)
            if not isinstance(widget, PaletteList):
                continue
            spec = widget.find_spec_by_template(template_id)
            if spec is None:
                continue
            previous_fill = QColor(spec.fill)
            if spec.fill != color:
                spec.fill = QColor(color)
                widget.refresh_spec_item(spec)
                previous = {"name": spec.name, "fill": previous_fill}
                self.handle_spec_changed(spec, previous)
            else:
                widget.refresh_spec_item(spec)
            return spec
        return None

    def handle_spec_changed(self, spec: ObjectSpec, previous: dict) -> None:
        ranks_to_update: Set[str] = set()
        if spec.name in RANK_ORDER:
            ranks_to_update.add(spec.name)
        previous_name = previous.get("name")
        if isinstance(previous_name, str) and previous_name in RANK_ORDER:
            ranks_to_update.add(previous_name)
        for rank in ranks_to_update:
            color = self.rank_template_color(rank)
            MemberData.update_rank_color_cache(rank, color)
            self.rank_spec_changed.emit(rank)

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
        self.active_member: Optional[MemberData] = None
        self._active_member_spec: Optional[ObjectSpec] = None

        # Sidebar (dock)
        self.palette_tabs = PaletteTabWidget(self)
        MemberData.set_palette_lookup(self.palette_tabs.rank_template_color)
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
        self.alliance_widget.members_tab.set_palette_widget(self.palette_tabs)
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
        self.scene.object_placed.connect(self._on_object_placed)
        self.scene.object_removed.connect(self._on_object_removed)

    def activate_placement(self, spec: ObjectSpec, clear_member: bool = True):
        if clear_member:
            self.active_member = None
            self._active_member_spec = None
        self.set_zone_draw_mode(False)
        self.scene.set_active_spec(spec)
        self.hint_label.setText(
            f"Placing {spec.name}: Left-click to place, Shift+Click for multiple, Right-click to cancel"
        )

    def activate_member(self, member: MemberData):
        spec = member.placement_spec()
        self._active_member_spec = spec
        self.activate_placement(spec, clear_member=False)
        self.active_member = member
        self.hint_label.setText(
            f"Placing {member.name} ({member.rank}): Left-click to place, Right-click to cancel"
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

    def _on_object_placed(self, obj: MapObject):
        template_id = getattr(obj.spec, "template_id", "")
        if template_id and template_id.startswith("member:"):
            self.alliance_widget.members_tab.handle_member_object_placed(template_id, obj)

    def _on_object_removed(self, obj: MapObject):
        template_id = getattr(obj.spec, "template_id", "")
        if template_id and template_id.startswith("member:"):
            self.alliance_widget.members_tab.handle_member_object_removed(template_id)

    def offer_apply_spec_changes(self, spec: ObjectSpec, previous: dict):
        matching: list[MapObject] = []
        for item in self.scene.items():
            if isinstance(item, MapObject) and item.spec.template_id == spec.template_id:
                matching.append(item)
        if not matching:
            return
        response = QMessageBox.question(
            self,
            "Update placed objects",
            "Apply these changes to existing objects of the same type?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if response != QMessageBox.Yes:
            return
        size_changed = (
            previous.get("size_w") != spec.size_w or previous.get("size_h") != spec.size_h
        )
        failed = False
        for obj in matching:
            obj.spec.name = spec.name
            obj.label_item.setText(spec.name)
            obj.updateLabelLayout()
            obj.spec.fill = QColor(spec.fill)
            obj.rect_item.setBrush(QBrush(obj.spec.fill))
            obj.spec.limit = spec.limit
            obj.spec.limit_key = spec.limit_key
            if size_changed:
                old_w = obj.spec.size_w
                old_h = obj.spec.size_h
                obj.spec.size_w = spec.size_w
                obj.spec.size_h = spec.size_h
                w_px = spec.size_w * self.scene.cell_size
                h_px = spec.size_h * self.scene.cell_size
                obj.rect_item.setRect(0, 0, w_px, h_px)
                obj.updateLabelLayout()
                self.scene.snap_items_to_grid([obj])
                if not self.scene.is_object_position_free(obj):
                    obj.spec.size_w = old_w
                    obj.spec.size_h = old_h
                    obj.rect_item.setRect(0, 0, old_w * self.scene.cell_size, old_h * self.scene.cell_size)
                    obj.updateLabelLayout()
                    self.scene.snap_items_to_grid([obj])
                    failed = True
                else:
                    obj._last_valid_pos = QPointF(obj.pos())
            else:
                obj._last_valid_pos = QPointF(obj.pos())
        if failed:
            QMessageBox.information(
                self,
                "Resize blocked",
                "Some objects could not be resized because they would overlap other items.",
            )
        self.scene.update()

    def clear_placement_hint(self):
        self.hint_label.setText("")

    def cancel_active_placement(self):
        any_cancelled = False
        if self.scene.active_spec is not None:
            self.scene.cancel_placement()
            any_cancelled = True
        self.active_member = None
        self._active_member_spec = None
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
