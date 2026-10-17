import ezdxf

from kolikesimapp.core.models import BoxParams, Material, Sheet
from kolikesimapp.core.geometry import generate_flat_pattern, LAYER_CUT, LAYER_FOLD, LAYER_MARK
from kolikesimapp.core.nesting import nest_single_pattern
from kolikesimapp.core.exporters import (
    export_flat_pattern_to_dxf,
    export_nested_sheet_to_dxf,
    export_flat_pattern_to_svg,
    export_nested_sheet_to_svg,
)


def test_export_flat_pattern_creates_valid_dxf(tmp_path):
    box = BoxParams("0201", 300, 200, 150)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    out_file = tmp_path / "test_box.dxf"
    export_flat_pattern_to_dxf(pattern, str(out_file))

    assert out_file.exists()

    doc = ezdxf.readfile(str(out_file))
    msp = doc.modelspace()
    lines = list(msp.query("LINE"))
    assert len(lines) == len(pattern.lines)

    layer_names = {layer.dxf.name for layer in doc.layers}
    assert {LAYER_CUT, LAYER_FOLD, LAYER_MARK}.issubset(layer_names)

    # Each line entity's layer matches one of our expected layers
    used_layers = {ln.dxf.layer for ln in lines}
    assert used_layers.issubset({LAYER_CUT, LAYER_FOLD, LAYER_MARK})


def test_export_nested_sheet_to_dxf(tmp_path):
    box = BoxParams("0201", 200, 150, 100)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    sheet = Sheet(width=1500, height=1000, margin=10, spacing=10)
    nesting_result = nest_single_pattern(pattern.width, pattern.height, sheet)
    assert nesting_result.count >= 1

    out_file = tmp_path / "nested_sheet.dxf"
    export_nested_sheet_to_dxf(
        pattern, nesting_result.placements, sheet.width, sheet.height, str(out_file)
    )

    assert out_file.exists()
    doc = ezdxf.readfile(str(out_file))
    msp = doc.modelspace()
    lines = list(msp.query("LINE"))

    # sheet boundary (4 lines) + count * lines-per-pattern
    expected = 4 + nesting_result.count * len(pattern.lines)
    assert len(lines) == expected


def test_export_nested_sheet_to_dxf_without_outline(tmp_path):
    box = BoxParams("0201", 200, 150, 100)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    sheet = Sheet(width=1500, height=1000, margin=10, spacing=10)
    nesting_result = nest_single_pattern(pattern.width, pattern.height, sheet)

    out_file = tmp_path / "nested_no_outline.dxf"
    export_nested_sheet_to_dxf(
        pattern, nesting_result.placements, sheet.width, sheet.height, str(out_file),
        include_sheet_outline=False,
    )

    doc = ezdxf.readfile(str(out_file))
    msp = doc.modelspace()
    lines = list(msp.query("LINE"))

    # no sheet boundary (4 lines) this time - only pattern copies
    expected = nesting_result.count * len(pattern.lines)
    assert len(lines) == expected
    assert "SHEET" not in {layer.dxf.name for layer in doc.layers}


def test_export_flat_pattern_to_svg(tmp_path):
    box = BoxParams("0201", 300, 200, 150)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    out_file = tmp_path / "test_box.svg"
    export_flat_pattern_to_svg(pattern, str(out_file))

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert content.startswith("<svg")
    assert content.count("<line") == len(pattern.lines)
    assert 'class="CUT"' in content
    assert 'class="FOLD"' in content


def test_export_nested_sheet_to_svg(tmp_path):
    box = BoxParams("0201", 200, 150, 100)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    sheet = Sheet(width=1500, height=1000, margin=10, spacing=10)
    nesting_result = nest_single_pattern(pattern.width, pattern.height, sheet)
    assert nesting_result.count >= 1

    out_file = tmp_path / "nested_sheet.svg"
    export_nested_sheet_to_svg(
        pattern, nesting_result.placements, sheet.width, sheet.height, str(out_file)
    )

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    # sheet rect + count * lines-per-pattern
    assert content.count("<line") == nesting_result.count * len(pattern.lines)
    assert 'class="SHEET"' in content


def test_svg_has_same_orientation_as_dxf(tmp_path):
    """SVG'de Y ekseni aşağı doğrudur; DXF ile aynı yönelim için çevrilmiş olmalı."""
    import re
    from kolikesimapp.core.exporters import export_flat_pattern_to_svg
    from kolikesimapp.core.geometry import FlatPattern, Line
    pat = FlatPattern(lines=[Line((0, 0), (10, 0), "CUT"), Line((0, 0), (0, 40), "CUT")], width=10, height=40)
    out = export_flat_pattern_to_svg(pat, str(tmp_path / "a.svg"))
    txt = open(out, encoding="utf-8").read()
    segs = [tuple(float(v) for v in m) for m in re.findall(r'x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', txt)]
    assert (0.0, 40.0, 10.0, 40.0) in segs   # DXF'teki (0,0)-(10,0) tabanı SVG'de alta (y=40) iner
    assert (0.0, 40.0, 0.0, 0.0) in segs
