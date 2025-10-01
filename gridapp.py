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
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QFont,
    QGuiApplication,
    QPainter,
    QPen,
    QColor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QInputDialog,
    QColorDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
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


DEFAULT_CATEGORIES: dict[str, list[ObjectSpec]] = {
    "Alliance": [
        ObjectSpec("Base", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("Outpost", 2, 2, QColor(Qt.cyan)),
        ObjectSpec("Resource", 2, 1, QColor(Qt.yellow)),
        ObjectSpec("Relay", 1, 1, QColor(Qt.green)),
    ]
}


def clone_spec(spec: ObjectSpec) -> ObjectSpec:
    return ObjectSpec(spec.name, spec.size_w, spec.size_h, QColor(spec.fill))


# ----------------------------- Map Items -------------------------------
class MapObject(QGraphicsItemGroup):
    def __init__(self, spec: ObjectSpec, top_left: QPointF, cell_size: int):
        super().__init__()
        self.spec = spec
        self.cell_size = cell_size

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

    def updateLabelLayout(self):
        w = self.spec.size_w * self.cell_size
        h = self.spec.size_h * self.cell_size
        label_rect = self.label_item.boundingRect()
        self.label_item.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

    def mouseDoubleClickEvent(self, event):
        # Rename via dialog
        new_name, ok = QInputDialog.getText(
            None, "Edit object", "Enter name:", text=self.label_item.text()
        )
        if ok and new_name.strip():
            final_name = new_name.strip()
            self.spec.name = final_name
            self.label_item.setText(final_name)
            self.updateLabelLayout()

        color = QColorDialog.getColor(self.spec.fill, None, "Choose color")
        if color.isValid():
            self.spec.fill = QColor(color)
            self.rect_item.setBrush(QBrush(self.spec.fill))

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

        if ok_w and ok_h:
            self.spec.size_w = width
            self.spec.size_h = height
            if isinstance(scene, MapScene):
                self.cell_size = scene.cell_size
            w = self.spec.size_w * self.cell_size
            h = self.spec.size_h * self.cell_size
            self.rect_item.setRect(0, 0, w, h)
            self.updateLabelLayout()
            if isinstance(scene, MapScene):
                scene.snap_map_objects_to_grid([self])
            else:
                current_top_left = self.pos()
                snapped_x = round(current_top_left.x() / self.cell_size) * self.cell_size
                snapped_y = round(current_top_left.y() / self.cell_size) * self.cell_size
                self.setPos(QPointF(snapped_x, snapped_y))

        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is None:
            return
        if isinstance(scene, MapScene):
            map_objects = [item for item in scene.selectedItems() if isinstance(item, MapObject)]
            if not map_objects:
                map_objects = [self]
            scene.snap_map_objects_to_grid(map_objects)
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


# ----------------------------- Scene/View ------------------------------
class MapScene(QGraphicsScene):
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
        self.preview_item: Optional[PreviewObject] = None

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

    def snap_map_objects_to_grid(self, objects: Iterable[MapObject]):
        cs = self.cell_size
        for obj in objects:
            if not isinstance(obj, MapObject):
                continue
            obj.cell_size = cs
            w = obj.spec.size_w * cs
            h = obj.spec.size_h * cs
            current_top_left = obj.pos()
            snapped_x = round(current_top_left.x() / cs) * cs
            snapped_y = round(current_top_left.y() / cs) * cs
            top_left = self._clamp_top_left(snapped_x, snapped_y, w, h)
            obj.setPos(top_left)

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

    def place_active_at(self, scene_pos: QPointF) -> Optional[MapObject]:
        if self.active_spec is None:
            return None
        pos = self._top_left_from_center_snap(scene_pos)
        obj = MapObject(clone_spec(self.active_spec), pos, self.cell_size)
        self.addItem(obj)
        obj.updateLabelLayout()
        return obj

    # --- Painting ---
    def drawBackground(self, painter: QPainter, rect: QRectF):
        # Draw grid behind items
        painter.fillRect(rect, QBrush(BACKGROUND_COLOR))
        if not self.show_grid:
            return
        cs = self.cell_size
        left = int(math.floor(rect.left() / cs))
        right = int(math.ceil(rect.right() / cs))
        top = int(math.floor(rect.top() / cs))
        bottom = int(math.ceil(rect.bottom() / cs))

        # Fine grid
        pen_fine = QPen(GRID_COLOR)
        pen_fine.setWidth(1)
        painter.setPen(pen_fine)
        for x in range(left, right + 1):
            px = x * cs
            painter.drawLine(px, rect.top(), px, rect.bottom())
        for y in range(top, bottom + 1):
            py = y * cs
            painter.drawLine(rect.left(), py, rect.right(), py)

        # Thicker lines every 10 cells
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

    def _map_object_from_item(self, item: Optional[QGraphicsItem]) -> Optional[MapObject]:
        while item is not None and not isinstance(item, MapObject):
            item = item.parentItem()
        return item if isinstance(item, MapObject) else None

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
            item_under_cursor = self._map_object_from_item(
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
        if self._panning:
            p = event.position()
            delta = QPointF(p.x(), p.y()) - self._pan_start
            self._pan_start = QPointF(p.x(), p.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        # Update preview position when moving mouse
        scene: MapScene = self.scene()
        p = event.position()
        scene.update_preview(self.mapToScene(int(p.x()), int(p.y())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
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
            to_remove: set[MapObject] = set()
            for item in scene.selectedItems():
                map_obj = self._map_object_from_item(item)
                if map_obj is not None:
                    to_remove.add(map_obj)
            if to_remove:
                for obj in to_remove:
                    scene.removeItem(obj)
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
            item = QListWidgetItem(f"{spec.name}  ({spec.size_w}x{spec.size_h})")
            item.setData(Qt.UserRole, spec)
            self.addItem(item)

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
        # Update list label
        item.setText(f"{spec.name}  ({spec.size_w}x{spec.size_h})")
        # If this spec is active, refresh preview
        w = self.window()
        if isinstance(w, MainWindow):
            w.refresh_active_preview_if(spec)


# ---------------------------- Palette Tabs ----------------------------
class PaletteTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)
        self.tabBarDoubleClicked.connect(self._rename_category)

        add_btn = QToolButton(self)
        add_btn.setText("+")
        add_btn.clicked.connect(self._prompt_new_category)
        self.setCornerWidget(add_btn, Qt.TopRightCorner)

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
        dock = QDockWidget("Objects", self)
        dock.setWidget(self.palette_tabs)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

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
        toolbar.addWidget(QLabel("Cell size:"))
        self.spin_cell = QSpinBox()
        self.spin_cell.setRange(5, 120)
        self.spin_cell.setValue(CELL_SIZE)
        self.spin_cell.valueChanged.connect(self.change_cell_size)
        toolbar.addWidget(self.spin_cell)

    def activate_placement(self, spec: ObjectSpec):
        self.scene.set_active_spec(spec)
        self.hint_label.setText(
            f"Placing {spec.name}: Left-click to place, Shift+Click for multiple, Right-click to cancel"
        )

    def refresh_active_preview_if(self, spec: ObjectSpec):
        if self.scene.active_spec is spec:
            self.scene.set_active_spec(spec)  # recreate preview with new name/color

    def clear_placement_hint(self):
        self.hint_label.setText("")

    def cancel_active_placement(self):
        if self.scene.active_spec is not None:
            self.scene.cancel_placement()
        self.clear_placement_hint()

    def toggle_grid(self, checked: bool):
        self.scene.show_grid = checked
        self.scene.update()

    def change_cell_size(self, v: int):
        # Rescale scene: update cell size, scene rect, and items
        self.scene.cell_size = v
        size_px = self.scene.cells * v
        self.scene.setSceneRect(0, 0, size_px, size_px)
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
            elif isinstance(item, PreviewObject):
                item.update_for_cell_size(v)
        self.scene.update()

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
            elif event.type() == QEvent.Leave:
                if self.scene.preview_item is not None:
                    self.scene.preview_item.setVisible(False)
            elif event.type() == QEvent.Enter:
                if self.scene.preview_item is not None:
                    self.scene.preview_item.setVisible(True)
        return super().eventFilter(watched, event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
