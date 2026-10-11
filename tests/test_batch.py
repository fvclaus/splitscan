import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from photo_splitter import telemetry
from photo_splitter.batch import Batch, ScanOutcome
from photo_splitter.domain import AmbiguousDetections, PhotoBoundary
from photo_splitter.main_window import MainWindow
from photo_splitter.widgets.batch_bar import BatchBar


def wait_for_job(app, window):
    deadline = time.monotonic() + 10
    while window._working and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window._working


def write_scan(path: Path) -> Path:
    image = np.full((350, 500, 3), 240, np.uint8)
    cv2.rectangle(image, (40, 40), (200, 280), (40, 100, 160), -1)
    cv2.rectangle(image, (270, 65), (460, 255), (120, 40, 80), -1)
    cv2.imwrite(str(path), image)
    return path


@pytest.fixture
def usage_events(monkeypatch):
    events = []
    monkeypatch.setattr(telemetry, "capture_usage", lambda *args: events.append(args))
    return events


@pytest.fixture
def dialogs(monkeypatch):
    shown = {"information": [], "warning": []}
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: shown["information"].append(args[2])
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown["warning"].append(args[2]))
    return shown


def choose(monkeypatch, paths):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([str(p) for p in paths], "")
    )


def test_natural_order_ignores_case_and_sorts_numbers_numerically():
    batch = Batch.from_paths([Path("scan-10.png"), Path("Scan-2.png"), Path("scan-1.png")])
    assert [path.name for path in batch.paths] == ["scan-1.png", "Scan-2.png", "scan-10.png"]


def test_batch_tracks_outcomes_and_remaining():
    batch = Batch.from_paths([Path(f"{n}.png") for n in "abcd"])
    assert (batch.index, batch.remaining, batch.is_last) == (0, 3, False)
    batch.record_exported(4)
    batch.advance()
    batch.record_skipped()
    batch.advance()
    batch.record_failed("bad file")
    assert batch.advance() == Path("d.png")
    assert batch.is_last and batch.remaining == 0
    assert batch.advance() is None
    assert batch.photos_exported == 4
    assert batch.names(ScanOutcome.SKIPPED) == ["b.png"]
    assert batch.failures == {2: "bad file"}


def test_batch_bar_summarises_progress_and_labels_segments(app):
    batch = Batch.from_paths([Path(f"scan-{n}.tif") for n in range(1, 10)])
    batch.record_exported(4)
    batch.advance()
    batch.record_skipped()
    batch.advance()
    batch.record_failed("x")
    batch.advance()
    bar = BatchBar()
    assert bar.isHidden()
    bar.set_batch(batch)
    assert bar.title_text == "Scan 4 of 9 · scan-4.tif"
    assert bar.counts_text == "1 exported · 1 skipped · 1 couldn't be read · 5 remaining"
    labels = [bar.strip.segment_label(index) for index in range(9)]
    assert labels[:5] == [
        "scan-1.tif · exported", "scan-2.tif · skipped", "scan-3.tif · could not be read",
        "scan-4.tif · reviewing", "scan-5.tif · up next",
    ]
    assert labels[8] == "scan-9.tif · waiting"
    bar.set_batch(None)
    assert bar.isHidden()


def test_batch_bar_moves_counts_below_segments_when_narrow(app):
    batch = Batch.from_paths([Path("a.png"), Path("b.png")])
    bar = BatchBar()
    bar.set_batch(batch)
    bar.resize(700, 80)
    bar.show()
    app.processEvents()
    assert bar.is_narrow
    bar.resize(1300, 80)
    app.processEvents()
    assert not bar.is_narrow
    bar.close()


def test_multi_select_runs_batch_with_export_next_skip_and_summary(
    app, tmp_path, monkeypatch, usage_events, dialogs
):
    scans = [write_scan(tmp_path / f"scan-{n}.png") for n in (10, 2, 1)]
    output = tmp_path / "out"
    output.mkdir()
    choose(monkeypatch, scans)
    window = MainWindow()
    window.show()
    window._output_directory = output
    window._choose_scan()
    wait_for_job(app, window)
    assert usage_events[0] == ("batch_started", 3)
    assert window._scan_path.name == "scan-1.png"
    assert not window.batch_bar.isHidden()
    assert window.batch_bar.title_text == "Scan 1 of 3 · scan-1.png"
    assert len(window.photo_grid.items) == 2
    assert window.export_button.text() == "Export 2 photos && next scan"
    assert window.skip_button.isVisible()

    window._export_selected()
    wait_for_job(app, window)
    assert window._scan_path.name == "scan-2.png"
    assert window.batch_bar.counts_text == "1 exported · 1 remaining"
    assert len(list(output.glob("*.jpg"))) == 2
    assert not dialogs["information"]

    window._skip_scan()
    wait_for_job(app, window)
    assert window._scan_path.name == "scan-10.png"
    assert window.export_button.text() == "Export 2 photos"

    window._export_selected()
    wait_for_job(app, window)
    assert window._batch is None
    assert window.batch_bar.isHidden()
    assert not window.skip_button.isVisible()
    assert len(list(output.glob("*.jpg"))) == 4
    (summary,) = dialogs["information"]
    assert "Exported 4 photos from 2 of 3 scans." in summary
    assert "Skipped (1): scan-2.png" in summary
    assert usage_events.count(("scan_loaded",)) == 3
    assert usage_events.count(("photos_extracted", 2)) == 3
    assert usage_events.count(("photos_saved", 2)) == 2
    assert [event for event in usage_events if event[0] == "batch_started"] == [("batch_started", 3)]
    window.close()


def test_unreadable_scans_are_skipped_and_listed(app, tmp_path, monkeypatch, usage_events, dialogs):
    good = write_scan(tmp_path / "a.png")
    broken = tmp_path / "b.png"
    broken.write_bytes(b"not an image")
    also_good = write_scan(tmp_path / "c.png")
    output = tmp_path / "out"
    output.mkdir()
    choose(monkeypatch, [good, broken, also_good])
    window = MainWindow()
    window._output_directory = output
    window._choose_scan()
    wait_for_job(app, window)
    window._export_selected()
    wait_for_job(app, window)
    assert window._scan_path.name == "c.png"
    assert not dialogs["warning"]
    window._export_selected()
    wait_for_job(app, window)
    (summary,) = dialogs["information"]
    assert "Exported 4 photos from 2 of 3 scans." in summary
    assert "Couldn't be read (1):" in summary and "b.png" in summary
    window.close()


def test_single_file_selection_is_not_a_batch(app, tmp_path, monkeypatch, usage_events, dialogs):
    choose(monkeypatch, [write_scan(tmp_path / "only.png")])
    window = MainWindow()
    window._choose_scan()
    wait_for_job(app, window)
    assert window._batch is None
    assert window.batch_bar.isHidden()
    assert not window.skip_button.isVisible()
    assert not any(event[0] == "batch_started" for event in usage_events)
    window.close()


def test_importing_during_batch_asks_before_stopping_it(app, tmp_path, monkeypatch, usage_events):
    scans = [write_scan(tmp_path / f"s{n}.png") for n in (1, 2)]
    choose(monkeypatch, scans)
    window = MainWindow()
    window._choose_scan()
    wait_for_job(app, window)
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *args: next(answers))
    window._choose_scan()
    assert window._batch is not None
    choose(monkeypatch, [scans[0]])
    window._choose_scan()
    wait_for_job(app, window)
    assert window._batch is None
    window.close()


def test_confirm_all_confirms_only_valid_suggestions(app, tmp_path):
    window = MainWindow()
    window.show()
    path = tmp_path / "scan.png"
    path.write_bytes(b"fixture")
    suggestions = tuple(
        PhotoBoundary(corners=((x, 30), (x + 100, 30), (x + 100, 250), (x, 250)), needs_review=True)
        for x in (10, 130)
    )
    invalid = PhotoBoundary(corners=((-10, 30), (90, 30), (90, 250), (-10, 250)), needs_review=True)
    window._accept_scan(
        path, np.full((300, 400, 3), 240, np.uint8),
        AmbiguousDetections(suggestions + (invalid,), "Review suggestions"),
    )
    assert window.confirm_all_button.isVisible()
    assert window.confirm_all_button.text() == "Confirm all (2)"
    window.confirm_all_button.click()
    assert all(item.user_confirmed for item in window._boundaries[:2])
    assert not window._boundaries[2].user_confirmed
    assert window.extract_button.text() == "Review 1 boundary"
    assert window._reviewing
    assert window.scan_view.selected_boundary_index == 2
    assert window.confirm_all_button.isHidden()
    assert not window._working
    window.close()


def test_confirm_all_hidden_without_suggestions_and_extracts_when_done(app, tmp_path):
    window = MainWindow()
    window.show()
    path = tmp_path / "scan.png"
    path.write_bytes(b"fixture")
    suggestions = tuple(
        PhotoBoundary(corners=((x, 30), (x + 100, 30), (x + 100, 250), (x, 250)), needs_review=True)
        for x in (10, 130)
    )
    window._accept_scan(
        path, np.full((300, 400, 3), 240, np.uint8), AmbiguousDetections(suggestions, "Review")
    )
    window._confirm_all_boundaries()
    assert window.confirm_all_button.isHidden()
    assert window.extract_button.isHidden()
    wait_for_job(app, window)
    assert len(window.photo_grid.items) == 2
    window._confirm_all_boundaries()
    window.close()


def test_edits_reextract_previews_automatically(app, tmp_path, monkeypatch, usage_events, dialogs):
    choose(monkeypatch, [write_scan(tmp_path / "scan.png")])
    window = MainWindow()
    window.show()
    window._choose_scan()
    wait_for_job(app, window)
    assert len(window.photo_grid.items) == 2
    window._exclude_review_boundary()
    wait_for_job(app, window)
    assert len(window.photo_grid.items) == 1
    window._set_all_boundaries_selected(False)
    assert not window.photo_grid.items and not window._working
    window._set_all_boundaries_selected(True)
    wait_for_job(app, window)
    assert len(window.photo_grid.items) == 2
    window.trim_borders.setChecked(False)
    wait_for_job(app, window)
    assert len(window.photo_grid.items) == 2
    assert usage_events.count(("photos_extracted", 2)) == 1
    window.close()
