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
from typing import Callable, Optional

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
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QLineEdit,
    QHBoxLayout,
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


DEFAULT_CATEGORIES: dict[str, list[ObjectSpec]] = {
    "Alliance": [
        ObjectSpec("Base", 3, 3, QColor(Qt.lightGray)),
        ObjectSpec("Outpost", 2, 2, QColor(Qt.cyan)),
        ObjectSpec("Resource", 2, 1, QColor(Qt.yellow)),
        ObjectSpec("Relay", 1, 1, QColor(Qt.green)),
    ]
}


def contrasting_text_color(color: QColor) -> QColor:
    if not color.isValid():
        return QColor(Qt.black)
    # Perceived brightness using standard luminance coefficients
    brightness = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor(Qt.black if brightness > 186 else Qt.white)


# ----------------------------- Map Items -------------------------------
class MapObject(QGraphicsItemGroup):
    def __init__(self, spec: ObjectSpec, top_left: QPointF, cell_size: int):
        super().__init__()
        self.spec = spec
        self.cell_size = cell_size

        # Individual properties copied from spec so each placed object can be
        # customized without mutating the shared template.
        self.width_cells = spec.size_w
        self.height_cells = spec.size_h
        self.fill_color = QColor(spec.fill)

        w = self.width_cells * cell_size
        h = self.height_cells * cell_size
        rect_item = QGraphicsRectItem(0, 0, w, h)
        rect_item.setBrush(QBrush(self.fill_color))
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
        self.update_geometry()

    def updateLabelLayout(self):
        w = self.width_cells * self.cell_size
        h = self.height_cells * self.cell_size
        label_rect = self.label_item.boundingRect()
        self.label_item.setPos((w - label_rect.width()) / 2, (h - label_rect.height()) / 2)

    def update_geometry(self):
        w = self.width_cells * self.cell_size
        h = self.height_cells * self.cell_size
        self.rect_item.setRect(0, 0, w, h)
        self.rect_item.setBrush(QBrush(self.fill_color))
        self.updateLabelLayout()

    def snap_to_grid(self):
        cs = self.cell_size
        w = self.width_cells * cs
        h = self.height_cells * cs
        center_x = self.pos().x() + w / 2
        center_y = self.pos().y() + h / 2
        i = round(center_x / cs - 0.5)
        j = round(center_y / cs - 0.5)
        snapped_center_x = (i + 0.5) * cs
        snapped_center_y = (j + 0.5) * cs
        new_x = snapped_center_x - w / 2
        new_y = snapped_center_y - h / 2
        self.setPos(QPointF(new_x, new_y))

    def mouseDoubleClickEvent(self, event):
        self.edit_properties()
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        targets: list[MapObject]
        if scene is not None:
            selected = [item for item in scene.selectedItems() if isinstance(item, MapObject)]
            if len(selected) > 1 and self in selected:
                targets = selected
            else:
                targets = [self]
        else:
            targets = [self]
        for item in targets:
            item.snap_to_grid()

    def edit_properties(self):
        parent = None
        scene = self.scene()
        if scene is not None and scene.views():
            parent = scene.views()[0].window()

        new_name, ok = QInputDialog.getText(
            parent, "Edit object name", "Enter name:", text=self.label_item.text()
        )
        if ok and new_name.strip():
            self.label_item.setText(new_name.strip())

        width, ok = QInputDialog.getInt(
            parent,
            "Edit width",
            "Width (cells):",
            self.width_cells,
            1,
            999,
        )
        if ok:
            self.width_cells = width

        height, ok = QInputDialog.getInt(
            parent,
            "Edit height",
            "Height (cells):",
            self.height_cells,
            1,
            999,
        )
        if ok:
            self.height_cells = height

        color = QColorDialog.getColor(self.fill_color, parent, "Choose color")
        if color.isValid():
            self.fill_color = QColor(color)

        self.update_geometry()
        self.snap_to_grid()

        if parent is not None and hasattr(parent, "refresh_selected_object_properties"):
            parent.refresh_selected_object_properties(self)


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

    def _top_left_from_center_snap(self, scene_pos: QPointF) -> QPointF:
        cs = self.cell_size
        spec = self.active_spec
        if spec is None:
            return QPointF(0, 0)
        w = spec.size_w * cs
        h = spec.size_h * cs
        # snap center to (i+0.5)*cs close to cursor
        i = round(scene_pos.x() / cs - 0.5)
        j = round(scene_pos.y() / cs - 0.5)
        snapped_center_x = (i + 0.5) * cs
        snapped_center_y = (j + 0.5) * cs
        x = snapped_center_x - w / 2
        y = snapped_center_y - h / 2
        # clamp inside scene
        x = max(0, min(self.scene_width() - w, x))
        y = max(0, min(self.scene_height() - h, y))
        return QPointF(x, y)

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
        obj = MapObject(self.active_spec, pos, self.cell_size)
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
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and (event.modifiers() & Qt.ShiftModifier)
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


# ----------------------------- Sidebar --------------------------------
class PaletteList(QListWidget):
    def __init__(self, specs: list[ObjectSpec], parent=None):
        super().__init__(parent)
        self.specs = specs
        self.setAlternatingRowColors(True)
        self.populate()
        self.itemClicked.connect(self._on_item_clicked)
        self.currentItemChanged.connect(self._on_current_item_changed)

    def _format_spec_label(self, spec: ObjectSpec) -> str:
        return f"{spec.name}  ({spec.size_w}x{spec.size_h})"

    def _create_item_for_spec(self, spec: ObjectSpec) -> QListWidgetItem:
        item = QListWidgetItem(self._format_spec_label(spec))
        item.setData(Qt.UserRole, spec)
        item.setBackground(QBrush(spec.fill))
        item.setForeground(QBrush(contrasting_text_color(spec.fill)))
        return item

    def add_spec(self, spec: ObjectSpec) -> QListWidgetItem:
        item = self._create_item_for_spec(spec)
        self.addItem(item)
        return item

    def populate(self):
        selected_spec: Optional[ObjectSpec] = None
        current = self.currentItem()
        if current is not None:
            selected_spec = current.data(Qt.UserRole)
        self.clear()
        target_item: Optional[QListWidgetItem] = None
        for spec in self.specs:
            item = self.add_spec(spec)
            if spec is selected_spec:
                target_item = item
        if target_item is not None:
            self.setCurrentItem(target_item)

    def current_spec(self) -> Optional[ObjectSpec]:
        item = self.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def refresh_item_for_spec(self, spec: ObjectSpec) -> Optional[QListWidgetItem]:
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) is spec:
                item.setText(self._format_spec_label(spec))
                item.setBackground(QBrush(spec.fill))
                item.setForeground(QBrush(contrasting_text_color(spec.fill)))
                item.setData(Qt.UserRole, spec)
                return item
        return None

    def _on_item_clicked(self, item: QListWidgetItem):
        spec: ObjectSpec = item.data(Qt.UserRole)
        w = self.window()
        if isinstance(w, MainWindow):
            w.activate_placement(spec)
            w.handle_palette_selection(spec, self)

    def _on_current_item_changed(self, current: Optional[QListWidgetItem], previous):
        spec = current.data(Qt.UserRole) if current is not None else None
        w = self.window()
        if isinstance(w, MainWindow):
            w.handle_palette_selection(spec, self)


# ---------------------------- Palette Tabs ----------------------------
class PaletteTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)
        self.tabBarDoubleClicked.connect(self._rename_category)
        self.currentChanged.connect(self._on_current_tab_changed)

        corner_widget = QWidget(self)
        layout = QHBoxLayout(corner_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        add_category_btn = QToolButton(corner_widget)
        add_category_btn.setText("+")
        add_category_btn.setToolTip("Add category")
        add_category_btn.clicked.connect(self._prompt_new_category)
        layout.addWidget(add_category_btn)

        add_object_btn = QToolButton(corner_widget)
        add_object_btn.setText("+Obj")
        add_object_btn.setToolTip("Add object to current category")
        add_object_btn.clicked.connect(self._prompt_new_object)
        layout.addWidget(add_object_btn)

        self.setCornerWidget(corner_widget, Qt.TopRightCorner)

        for name, specs in DEFAULT_CATEGORIES.items():
            self.add_category(name, specs)

    def add_category(self, name: str, specs: Optional[list[ObjectSpec]] = None):
        if specs is None:
            specs = []
        list_widget = PaletteList(specs, self)
        self.addTab(list_widget, name)
        return list_widget

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
        width, ok = QInputDialog.getInt(self, "Add Object", "Width (cells):", 1, 1, 999)
        if not ok:
            return
        height, ok = QInputDialog.getInt(self, "Add Object", "Height (cells):", 1, 1, 999)
        if not ok:
            return
        color = QColorDialog.getColor(QColor(Qt.lightGray), self, "Choose color")
        if not color.isValid():
            return
        spec = ObjectSpec(name, width, height, QColor(color))
        self.add_object_to_index(index, spec)

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

    def add_object_to_tab(self, name: str, spec: ObjectSpec) -> bool:
        for i in range(self.count()):
            if self.tabText(i).lower() == name.lower():
                return self.add_object_to_index(i, spec)
        return False

    def add_object_to_index(self, index: int, spec: ObjectSpec) -> bool:
        if 0 <= index < self.count():
            widget = self.widget(index)
            if isinstance(widget, PaletteList):
                widget.specs.append(spec)
                item = widget.add_spec(spec)
                widget.setCurrentItem(item)
                w = self.window()
                if isinstance(w, MainWindow):
                    w.handle_palette_selection(spec, widget)
                return True
        return False

    def _on_current_tab_changed(self, index: int):
        widget = self.widget(index) if 0 <= index < self.count() else None
        spec = widget.current_spec() if isinstance(widget, PaletteList) else None
        w = self.window()
        if isinstance(w, MainWindow):
            w.handle_palette_selection(spec, widget if isinstance(widget, PaletteList) else None)


# ------------------------- Property Editor Panel -----------------------
class ObjectPropertyEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self.default_group = QGroupBox("Default object settings", self)
        layout.addWidget(self.default_group)
        default_form = QFormLayout(self.default_group)
        default_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.default_name = QLineEdit(self.default_group)
        self.default_width = QSpinBox(self.default_group)
        self.default_height = QSpinBox(self.default_group)
        self.default_color = QToolButton(self.default_group)
        self.default_color.setText("Choose…")
        self.default_width.setRange(1, 999)
        self.default_height.setRange(1, 999)
        default_form.addRow("Name", self.default_name)
        default_form.addRow("Width", self.default_width)
        default_form.addRow("Height", self.default_height)
        default_form.addRow("Color", self.default_color)

        self.selected_group = QGroupBox("Selected map object", self)
        layout.addWidget(self.selected_group)
        selected_form = QFormLayout(self.selected_group)
        selected_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.selected_name = QLineEdit(self.selected_group)
        self.selected_width = QSpinBox(self.selected_group)
        self.selected_height = QSpinBox(self.selected_group)
        self.selected_color = QToolButton(self.selected_group)
        self.selected_color.setText("Choose…")
        self.selected_width.setRange(1, 999)
        self.selected_height.setRange(1, 999)
        selected_form.addRow("Name", self.selected_name)
        selected_form.addRow("Width", self.selected_width)
        selected_form.addRow("Height", self.selected_height)
        selected_form.addRow("Color", self.selected_color)

        layout.addStretch(1)

        self._current_spec: Optional[ObjectSpec] = None
        self._spec_changed: Optional[Callable[[ObjectSpec], None]] = None
        self._current_object: Optional[MapObject] = None
        self._block_default = False
        self._block_selected = False

        self.default_group.setEnabled(False)
        self.selected_group.setEnabled(False)

        self.default_name.editingFinished.connect(self._commit_default_name)
        self.default_width.valueChanged.connect(self._commit_default_width)
        self.default_height.valueChanged.connect(self._commit_default_height)
        self.default_color.clicked.connect(self._choose_default_color)

        self.selected_name.editingFinished.connect(self._commit_selected_name)
        self.selected_width.valueChanged.connect(self._commit_selected_width)
        self.selected_height.valueChanged.connect(self._commit_selected_height)
        self.selected_color.clicked.connect(self._choose_selected_color)

    def _set_button_color(self, button: QToolButton, color: QColor):
        if not color.isValid():
            button.setStyleSheet("")
            return
        button.setStyleSheet(
            "QToolButton {"
            f"background-color: {color.name()};"
            "border: 1px solid #444;"
            "min-width: 48px;"
            "}"
        )

    def set_default_spec(self, spec: Optional[ObjectSpec], on_changed: Optional[Callable[[ObjectSpec], None]] = None):
        self._current_spec = spec
        self._spec_changed = on_changed
        if spec is None:
            self._block_default = True
            self.default_name.clear()
            self.default_width.setValue(1)
            self.default_height.setValue(1)
            self._set_button_color(self.default_color, QColor())
            self._block_default = False
            self.default_group.setEnabled(False)
            return

        self._block_default = True
        self.default_name.setText(spec.name)
        self.default_width.setValue(spec.size_w)
        self.default_height.setValue(spec.size_h)
        self._set_button_color(self.default_color, spec.fill)
        self._block_default = False
        self.default_group.setEnabled(True)

    def set_selected_object(self, obj: Optional[MapObject]):
        self._current_object = obj
        if obj is None:
            self._block_selected = True
            self.selected_name.clear()
            self.selected_width.setValue(1)
            self.selected_height.setValue(1)
            self._set_button_color(self.selected_color, QColor())
            self._block_selected = False
            self.selected_group.setEnabled(False)
            return

        self._block_selected = True
        self.selected_name.setText(obj.label_item.text())
        self.selected_width.setValue(obj.width_cells)
        self.selected_height.setValue(obj.height_cells)
        self._set_button_color(self.selected_color, obj.fill_color)
        self._block_selected = False
        self.selected_group.setEnabled(True)

    def refresh_selected_object(self, obj: MapObject):
        if obj is self._current_object:
            self.set_selected_object(obj)

    def refresh_default_spec(self, spec: ObjectSpec):
        if spec is self._current_spec:
            self.set_default_spec(spec, self._spec_changed)

    def _notify_spec_changed(self):
        if self._spec_changed is not None and self._current_spec is not None:
            self._spec_changed(self._current_spec)

    def _commit_default_name(self):
        if self._block_default or self._current_spec is None:
            return
        text = self.default_name.text().strip()
        if not text:
            self.default_name.setText(self._current_spec.name)
            return
        if text != self._current_spec.name:
            self._current_spec.name = text
            self._notify_spec_changed()

    def _commit_default_width(self, value: int):
        if self._block_default or self._current_spec is None:
            return
        if value != self._current_spec.size_w:
            self._current_spec.size_w = value
            self._notify_spec_changed()

    def _commit_default_height(self, value: int):
        if self._block_default or self._current_spec is None:
            return
        if value != self._current_spec.size_h:
            self._current_spec.size_h = value
            self._notify_spec_changed()

    def _choose_default_color(self):
        if self._current_spec is None:
            return
        color = QColorDialog.getColor(self._current_spec.fill, self, "Choose default color")
        if color.isValid():
            self._current_spec.fill = QColor(color)
            self._set_button_color(self.default_color, self._current_spec.fill)
            self._notify_spec_changed()

    def _commit_selected_name(self):
        if self._block_selected or self._current_object is None:
            return
        text = self.selected_name.text().strip()
        if not text:
            self.selected_name.setText(self._current_object.label_item.text())
            return
        if text != self._current_object.label_item.text():
            self._current_object.label_item.setText(text)
            self._current_object.updateLabelLayout()

    def _commit_selected_width(self, value: int):
        if self._block_selected or self._current_object is None:
            return
        if value != self._current_object.width_cells:
            self._current_object.width_cells = value
            self._current_object.update_geometry()
            self._current_object.snap_to_grid()

    def _commit_selected_height(self, value: int):
        if self._block_selected or self._current_object is None:
            return
        if value != self._current_object.height_cells:
            self._current_object.height_cells = value
            self._current_object.update_geometry()
            self._current_object.snap_to_grid()

    def _choose_selected_color(self):
        if self._current_object is None:
            return
        color = QColorDialog.getColor(self._current_object.fill_color, self, "Choose object color")
        if color.isValid():
            self._current_object.fill_color = QColor(color)
            self._current_object.update_geometry()
            self._set_button_color(self.selected_color, self._current_object.fill_color)

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
        self.property_editor = ObjectPropertyEditor(self)
        sidebar = QWidget(self)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        sidebar_layout.addWidget(self.palette_tabs, 1)
        sidebar_layout.addWidget(self.property_editor, 0)

        dock = QDockWidget("Objects", self)
        dock.setWidget(sidebar)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # Status bar with coordinates + hint
        self.coord_label = QLabel("x: -, y: -")
        self.hint_label = QLabel("")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().addPermanentWidget(self.hint_label)
        self.view.setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        self.scene.selectionChanged.connect(self._on_selection_changed)

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

        first_widget = self.palette_tabs.widget(0)
        if isinstance(first_widget, PaletteList) and first_widget.count() > 0:
            first_widget.setCurrentRow(0)

    def activate_placement(self, spec: ObjectSpec):
        self.scene.set_active_spec(spec)
        self.hint_label.setText(
            f"Placing {spec.name}: Left-click to place, Shift+Click for multiple, Right-click to cancel"
        )

    def refresh_active_preview_if(self, spec: ObjectSpec):
        if self.scene.active_spec is spec:
            self.scene.set_active_spec(spec)  # recreate preview with new name/color

    def handle_palette_selection(self, spec: Optional[ObjectSpec], list_widget: Optional[PaletteList]):
        if spec is None or list_widget is None:
            self.property_editor.set_default_spec(None)
            return

        def on_changed(updated_spec: ObjectSpec):
            item = list_widget.refresh_item_for_spec(updated_spec)
            if item is not None:
                list_widget.setCurrentItem(item)
            self.refresh_active_preview_if(updated_spec)

        self.property_editor.set_default_spec(spec, on_changed)

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
                item.update_geometry()
                item.snap_to_grid()
            elif isinstance(item, PreviewObject):
                item.update_for_cell_size(v)
        self.scene.update()

    def _on_selection_changed(self):
        selected = [item for item in self.scene.selectedItems() if isinstance(item, MapObject)]
        if len(selected) == 1:
            self.property_editor.set_selected_object(selected[0])
        else:
            self.property_editor.set_selected_object(None)

    def refresh_selected_object_properties(self, obj: MapObject):
        self.property_editor.refresh_selected_object(obj)

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
