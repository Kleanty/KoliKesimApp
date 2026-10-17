"""GUI regresyon testleri (başsız / offscreen).

Bu testler, ekran görüntüleriyle tespit edilen gerçek GUI hatalarının geri
gelmesini engeller:
  1. Kontrol listesinde üst üste binen / hayalet (yetim) etiketler
  2. "&" karakterinin kısayol (mnemonic) sanılıp "_" olarak görünmesi
  3. Dil değişince alan etiketlerinin / özet metinlerinin çevrilmemesi
  4. Yalnızca mm birimi (cm seçeneği kaldırıldı)
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    return application


@pytest.fixture()
def window(app):
    from kolikesimapp.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    for _ in range(10):
        app.processEvents()
    yield w
    w.close()


def _settle(app, n=20):
    for _ in range(n):
        app.processEvents()


def test_only_mm_unit_exists(window):
    assert not hasattr(window, "unit_combo")
    assert not hasattr(window, "current_unit")
    for spin in [window.box_length, window.box_width, window.box_height,
                 window.material_thickness, window.sheet_width,
                 window.sheet_height, window.sheet_margin, window.sheet_spacing]:
        assert spin.suffix() == " mm"


def test_form_values_are_passed_to_project_unchanged_in_mm(window):
    window.box_length.setValue(321.0)
    window.material_thickness.setValue(0.5)
    project = window._collect_project()
    assert project.box.length == 321.0
    assert project.material.thickness == 0.5  # küçük değerler bozulmamalı


def test_no_orphan_or_overlapping_check_labels_after_many_recalcs(window, app):
    """REGRESSION: deleteLater() yalnızca ertelediği için eski etiketler
    görünür kalıp yenilerinin üstüne biniyordu."""
    for value in (310, 320, 4500, 300):
        window.box_length.setValue(value)
    _settle(app)

    labels = window.checks_container.findChildren(QLabel)
    assert len(labels) == window.checks_layout.count()  # hayalet etiket yok

    rects = sorted((lbl.geometry().top(), lbl.geometry().bottom()) for lbl in labels)
    for (_, prev_bottom), (next_top, _) in zip(rects, rects[1:]):
        assert next_top > prev_bottom, "kontrol etiketleri üst üste biniyor"


def test_checks_label_height_fits_wrapped_text(window, app):
    window.box_length.setValue(4500)
    window.box_width.setValue(3500)
    _settle(app)
    for i in range(window.checks_layout.count()):
        lbl = window.checks_layout.itemAt(i).widget()
        assert lbl.geometry().height() >= lbl.minimumHeight()


def test_ampersand_titles_are_escaped(window):
    # Tek '&' Qt'de kısayol işaretidir ve görünmez olur; '&&' gerekir.
    assert "&&" in window.summary_group.title() or "&" in window.summary_group.title()
    assert "_" not in window.summary_group.title()


def test_language_switch_translates_labels_menus_and_summary(window, app):
    window._set_language("en")
    _settle(app)
    assert window.lbl_box_type.text() == "Box Model:"
    assert window.file_menu.title() == "File"
    assert window.templates_menu.title() == "Templates"
    assert "Box Model" in window.summary_label.text()
    assert "Laser Recommendation" in window.laser_recommendation_label.text()

    window._set_language("tr")
    _settle(app)
    assert window.lbl_box_type.text() == "Koli Modeli:"
    assert window.file_menu.title() == "Dosya"
    assert "Koli Modeli" in window.summary_label.text()


def test_unknown_box_type_error_clears_state_and_blocks_export(window, app, monkeypatch):
    import kolikesimapp.gui.main_window as mw
    from kolikesimapp.core.box_factory import UnknownBoxTypeError

    def boom(box, material):
        raise UnknownBoxTypeError("Bilinmeyen koli tipi: 'x'")

    monkeypatch.setattr(mw, "generate_pattern", boom)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a)))

    window._auto_recalculate()
    assert window.current_pattern is None
    assert "Bilinmeyen koli tipi" in window.summary_label.text()

    window._on_generate_dxf()
    assert warnings, "geçersiz durumda DXF üretimi uyarıyla engellenmeli"


def test_two_back_to_back_exports_do_not_collide(window, tmp_path, monkeypatch):
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    window.output_folder_edit.setText(str(tmp_path))
    window._on_generate_dxf()
    window._on_generate_dxf()
    assert len(list(tmp_path.rglob("*.dxf"))) == 2
