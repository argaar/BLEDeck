"""QDialog for recording and editing a macro for one key."""
from __future__ import annotations
import logging
import threading

from PyQt5.QtCore import Qt, pyqtSignal, QObject, QVariant
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox,
)

import macro_player
from macro_models import ClickStep, KeyStep, MacroStep, SleepStep, step_description
from macro_recorder import MacroRecorder

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
class _StepEditDialog(QDialog):
    """Type-aware editor for a single MacroStep."""

    def __init__(self, step: MacroStep, parent=None) -> None:
        super().__init__(parent)
        self._step = step
        layout = QVBoxLayout(self)

        if isinstance(step, SleepStep):
            self.setWindowTitle("Edit Wait Step")
            row = QHBoxLayout()
            row.addWidget(QLabel("Duration (ms):"))
            self._duration = QSpinBox()
            self._duration.setRange(1, 300_000)
            self._duration.setValue(step.duration_ms)
            row.addWidget(self._duration)
            layout.addLayout(row)

        elif isinstance(step, ClickStep):
            self.setWindowTitle("Edit Click Step")
            for label, attr, lo, hi in [("X:", "x", -9999, 9999),
                                         ("Y:", "y", -9999, 9999)]:
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                spin = QSpinBox()
                spin.setRange(lo, hi)
                spin.setValue(getattr(step, attr))
                row.addWidget(spin)
                layout.addLayout(row)
                setattr(self, f"_{attr}_spin", spin)
            btn_row = QHBoxLayout()
            btn_row.addWidget(QLabel("Button:"))
            self._btn_combo = QComboBox()
            self._btn_combo.addItems(["left", "right", "middle"])
            self._btn_combo.setCurrentText(step.button)
            btn_row.addWidget(self._btn_combo)
            layout.addLayout(btn_row)
            anchor_row = QHBoxLayout()
            anchor_row.addWidget(QLabel("Relative to:"))
            self._anchor_edit = QLineEdit(step.relative_to)
            self._anchor_edit.setToolTip(
                'e.g.  "window:Calculator"  "monitor:0"  "abs"'
            )
            anchor_row.addWidget(self._anchor_edit)
            layout.addLayout(anchor_row)

        elif isinstance(step, KeyStep):
            self.setWindowTitle("Edit Key Step")
            key_row = QHBoxLayout()
            key_row.addWidget(QLabel("Key:"))
            self._key_edit = QLineEdit(step.key)
            key_row.addWidget(self._key_edit)
            layout.addLayout(key_row)
            layout.addWidget(QLabel("Modifiers:"))
            self._ctrl_cb  = QCheckBox("Ctrl");  self._ctrl_cb.setChecked("ctrl"  in step.modifiers)
            self._shift_cb = QCheckBox("Shift"); self._shift_cb.setChecked("shift" in step.modifiers)
            self._alt_cb   = QCheckBox("Alt");   self._alt_cb.setChecked("alt"   in step.modifiers)
            self._win_cb   = QCheckBox("Win");   self._win_cb.setChecked("win"   in step.modifiers)
            for cb in (self._ctrl_cb, self._shift_cb, self._alt_cb, self._win_cb):
                layout.addWidget(cb)

        ok_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_row.addWidget(ok_btn)
        ok_row.addWidget(cancel_btn)
        layout.addLayout(ok_row)

    def get_step(self) -> MacroStep:
        if isinstance(self._step, SleepStep):
            return SleepStep(duration_ms=self._duration.value())
        if isinstance(self._step, ClickStep):
            return ClickStep(
                x=self._x_spin.value(),
                y=self._y_spin.value(),
                button=self._btn_combo.currentText(),
                relative_to=self._anchor_edit.text(),
            )
        if isinstance(self._step, KeyStep):
            mods = [m for m, cb in (("ctrl",  self._ctrl_cb),
                                    ("shift", self._shift_cb),
                                    ("alt",   self._alt_cb),
                                    ("win",   self._win_cb))
                    if cb.isChecked()]
            key = self._key_edit.text().strip() or self._step.key
            return KeyStep(key=key, modifiers=tuple(mods))
        return self._step


# ------------------------------------------------------------------
class _Signals(QObject):
    # Carries list[MacroStep]; PyQt5 routes cross-thread emissions as queued.
    recording_done = pyqtSignal(list)


class MacroDialog(QDialog):
    # Emitted (queued) when a Test Run thread finishes, so the button can be
    # safely re-enabled on the GUI thread.
    test_run_finished = pyqtSignal()

    def __init__(self, key_label: str, existing_steps: list[MacroStep],
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Macro — Key {key_label}")
        self.setMinimumWidth(460)

        self._steps: list[MacroStep] = list(existing_steps)
        self._recorder: MacroRecorder | None = None
        self._signals = _Signals()
        self._signals.recording_done.connect(self._on_recording_done)
        self._test_btn: QPushButton | None = None
        self.test_run_finished.connect(self._on_test_run_finished)

        layout = QVBoxLayout(self)

        self._recording_label = QLabel()
        self._recording_label.setAlignment(Qt.AlignCenter)  # pyright: ignore[reportAttributeAccessIssue]
        self._recording_label.setStyleSheet(
            "color: red; font-weight: bold; font-size: 13px;"
        )
        layout.addWidget(self._recording_label)

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.InternalMove)  # pyright: ignore[reportAttributeAccessIssue]
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._list.itemDoubleClicked.connect(self._edit_selected)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()

        self._record_btn = QPushButton("Record")
        self._record_btn.clicked.connect(self._start_recording)
        btn_row.addWidget(self._record_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_recording)
        btn_row.addWidget(self._stop_btn)

        test_btn = QPushButton("Test Run")
        test_btn.clicked.connect(self._test_run)
        btn_row.addWidget(test_btn)
        self._test_btn = test_btn

        edit_btn = QPushButton("Edit Step")
        edit_btn.clicked.connect(lambda: self._edit_selected())
        btn_row.addWidget(edit_btn)

        del_btn = QPushButton("Delete Step")
        del_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(del_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        ok_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_row.addWidget(ok_btn)
        ok_row.addWidget(cancel_btn)
        layout.addLayout(ok_row)

        self._refresh_list()

    # ------------------------------------------------------------------
    def _refresh_list(self) -> None:
        self._list.clear()
        for i, step in enumerate(self._steps):
            item = QListWidgetItem(f"{i + 1}. {step_description(step)}")
            item.setData(Qt.UserRole, QVariant(step))  # pyright: ignore[reportAttributeAccessIssue]
            self._list.addItem(item)

    def _on_rows_moved(self, *_) -> None:
        """Rebuild _steps from widget order after a drag-reorder."""
        new_steps: list[MacroStep] = []
        for i in range(self._list.count()):
            step = self._list.item(i).data(Qt.UserRole)  # pyright: ignore[reportAttributeAccessIssue]
            if step is not None:
                new_steps.append(step)
        self._steps = new_steps
        self._refresh_list()

    # ------------------------------------------------------------------
    def _start_recording(self) -> None:
        self._recording_label.setText("● RECORDING — press Esc to stop")
        self._record_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._recorder = MacroRecorder(on_done=self._signals.recording_done.emit)
        self._recorder.start()

    def _stop_recording(self) -> None:
        if self._recorder:
            self._recorder.stop()

    def _on_recording_done(self, steps: list[MacroStep]) -> None:
        self._recording_label.setText("")
        self._record_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._recorder = None
        if steps:
            self._steps = steps
            self._refresh_list()

    # ------------------------------------------------------------------
    def _edit_selected(self, _item=None) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        dialog = _StepEditDialog(self._steps[row], parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self._steps[row] = dialog.get_step()
            self._refresh_list()
            self._list.setCurrentRow(row)

    def _test_run(self) -> None:
        if not self._steps:
            QMessageBox.information(self, "No Steps", "Record a macro first.")
            return
        steps = list(self._steps)
        if self._test_btn is not None:
            self._test_btn.setEnabled(False)

        def _worker() -> None:
            try:
                macro_player.play(steps)
            except Exception:
                logger.exception("Test Run macro playback failed")
            finally:
                # Signal is cross-thread safe (queued connection).
                self.test_run_finished.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_test_run_finished(self) -> None:
        if self._test_btn is not None:
            self._test_btn.setEnabled(True)

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._steps.pop(row)
            self._refresh_list()

    def _clear(self) -> None:
        self._steps = []
        self._refresh_list()

    # ------------------------------------------------------------------
    def get_steps(self) -> list[MacroStep]:
        return list(self._steps)
