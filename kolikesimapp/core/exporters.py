"""
DXF / SVG üretim modülü
DXF & SVG export module

Gerçek ölçekte (mm), CUT/FOLD/MARK katmanlı,
üretime uygun DXF ve SVG dosyaları üretir.

DXF  -> ana üretim çıktısı
SVG  -> önizleme / uyumlu lazer çıktısı

Yapay zeka içermez.
"""

from pathlib import Path

import ezdxf

from .geometry import (
    FlatPattern,
    LAYER_CUT,
    LAYER_FOLD,
    LAYER_MARK,
)


# ============================================================================
# KATMAN RENKLERİ (DXF / ACI)
# ============================================================================

_LAYER_COLORS = {
    LAYER_CUT: 1,       # Red
    LAYER_FOLD: 5,      # Blue
    LAYER_MARK: 3,      # Green
    "SHEET": 8,         # Gray
}


# ============================================================================
# KATMAN ÇİZGİ TİPLERİ (DXF)
# ============================================================================

_LAYER_LINETYPES = {
    LAYER_CUT: "CONTINUOUS",
    LAYER_FOLD: "DASHED",
    LAYER_MARK: "DASHDOT",
    "SHEET": "CONTINUOUS",
}


# ============================================================================
# SVG SATIR İÇİ (INLINE) STİLLERİ - Lazer Yazılımları İle %100 Uyumluluk
# ============================================================================

_SVG_INLINE_STYLES = {
    LAYER_CUT: 'stroke="#E53935" stroke-width="0.5" fill="none"',
    LAYER_FOLD: 'stroke="#1976D2" stroke-width="0.5" fill="none" stroke-dasharray="4,2"',
    LAYER_MARK: 'stroke="#2E7D32" stroke-width="0.5" fill="none" stroke-dasharray="2,2"',
    "SHEET": 'stroke="#777777" stroke-width="0.5" fill="none" stroke-dasharray="8,4"',
}


# ============================================================================
# DXF DOKÜMANI HAZIRLAMA
# ============================================================================

def _create_dxf_document():
    """
    Yeni DXF dokümanı oluşturur.

    Birimler:
        mm

    Layer:
        CUT
        FOLD
        MARK
        SHEET
    """

    doc = ezdxf.new(
        dxfversion="R2010"
    )

    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = ezdxf.units.MM

    if "DASHED" not in doc.linetypes:
        doc.linetypes.add(
            "DASHED",
            pattern=[0.6, 0.4, -0.2],
        )

    if "DASHDOT" not in doc.linetypes:
        doc.linetypes.add(
            "DASHDOT",
            pattern=[0.6, 0.4, -0.1, 0.0, -0.1],
        )

    for layer_name in (
        LAYER_CUT,
        LAYER_FOLD,
        LAYER_MARK,
    ):
        if layer_name not in doc.layers:
            doc.layers.add(
                name=layer_name,
                color=_LAYER_COLORS[layer_name],
                linetype=_LAYER_LINETYPES[layer_name],
            )

    return doc


# ============================================================================
# FLAT PATTERN -> DXF
# ============================================================================

def export_flat_pattern_to_dxf(
    pattern: FlatPattern,
    filepath: str,
) -> str:
    """
    Tek bir FlatPattern nesnesini DXF olarak kaydeder.
    """

    doc = _create_dxf_document()
    modelspace = doc.modelspace()

    for line in pattern.lines:
        if line.layer not in (
            LAYER_CUT,
            LAYER_FOLD,
            LAYER_MARK,
        ):
            continue

        modelspace.add_line(
            line.p1,
            line.p2,
            dxfattribs={
                "layer": line.layer,
            },
        )

    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(output_path))

    return str(output_path)


# ============================================================================
# NESTED SHEET -> DXF
# ============================================================================

def export_nested_sheet_to_dxf(
    pattern: FlatPattern,
    placements,
    sheet_width: float,
    sheet_height: float,
    filepath: str,
    include_sheet_outline: bool = True,
) -> str:
    """
    Nesting sonucunu tek DXF dosyasına aktarır.
    """

    doc = _create_dxf_document()
    modelspace = doc.modelspace()

    if include_sheet_outline:
        if "SHEET" not in doc.layers:
            doc.layers.add(
                name="SHEET",
                color=_LAYER_COLORS["SHEET"],
                linetype=_LAYER_LINETYPES["SHEET"],
            )

        sheet_corners = [
            (0.0, 0.0),
            (sheet_width, 0.0),
            (sheet_width, sheet_height),
            (0.0, sheet_height),
            (0.0, 0.0),
        ]

        for p1, p2 in zip(
            sheet_corners[:-1],
            sheet_corners[1:],
        ):
            modelspace.add_line(
                p1,
                p2,
                dxfattribs={
                    "layer": "SHEET",
                },
            )

    pattern_width = pattern.width

    for placement in placements:
        offset_x = placement.x
        offset_y = placement.y
        rotated = bool(placement.rotated)

        for line in pattern.lines:
            p1 = line.p1
            p2 = line.p2

            if rotated:
                p1 = (
                    p1[1],
                    pattern_width - p1[0],
                )
                p2 = (
                    p2[1],
                    pattern_width - p2[0],
                )

            transformed_p1 = (
                p1[0] + offset_x,
                p1[1] + offset_y,
            )
            transformed_p2 = (
                p2[0] + offset_x,
                p2[1] + offset_y,
            )

            if line.layer not in (
                LAYER_CUT,
                LAYER_FOLD,
                LAYER_MARK,
            ):
                continue

            modelspace.add_line(
                transformed_p1,
                transformed_p2,
                dxfattribs={
                    "layer": line.layer,
                },
            )

    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(output_path))

    return str(output_path)


# ============================================================================
# FLAT PATTERN -> SVG (Inline Style)
# ============================================================================

def export_flat_pattern_to_svg(
    pattern: FlatPattern,
    filepath: str,
) -> str:
    """
    Tek bir flat pattern'i SVG olarak dışa aktarır.
    LaserWeb/LaserGRBL uyumu için inline stil kullanılır.
    """

    width = pattern.width
    height = pattern.height

    svg_lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {width} {height}" '
            f'width="{width}mm" '
            f'height="{height}mm">'
        ),
        '  <g id="FlatPattern">',
    ]

    for line in pattern.lines:
        if line.layer not in (
            LAYER_CUT,
            LAYER_FOLD,
            LAYER_MARK,
        ):
            continue

        x1, y1 = round(line.p1[0], 4), round(height - line.p1[1], 4)   # SVG'de Y aşağı doğru; DXF ile aynı yönelim için çevir
        x2, y2 = round(line.p2[0], 4), round(height - line.p2[1], 4)
        style_attr = _SVG_INLINE_STYLES.get(line.layer, "")

        svg_lines.append(
            (
                f'    <line '
                f'x1="{x1}" '
                f'y1="{y1}" '
                f'x2="{x2}" '
                f'y2="{y2}" '
                f'class="{line.layer}" '
                f'{style_attr} />'
            )
        )

    svg_lines.append("  </g>")
    svg_lines.append("</svg>")

    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write("\n".join(svg_lines))

    return str(output_path)


# ============================================================================
# NESTED SHEET -> SVG (Inline Style)
# ============================================================================

def export_nested_sheet_to_svg(
    pattern: FlatPattern,
    placements,
    sheet_width: float,
    sheet_height: float,
    filepath: str,
    include_sheet_outline: bool = True,
) -> str:
    """
    Nesting sonucunu tek SVG dosyasına aktarır.
    LaserWeb/LaserGRBL uyumu için inline stil kullanılır.
    """

    pattern_width = pattern.width

    svg_lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {sheet_width} {sheet_height}" '
            f'width="{sheet_width}mm" '
            f'height="{sheet_height}mm">'
        ),
    ]

    # Levha sınırı
    if include_sheet_outline:
        sheet_style = _SVG_INLINE_STYLES["SHEET"]
        svg_lines.append(
            (
                f'  <rect '
                f'x="0" '
                f'y="0" '
                f'width="{sheet_width}" '
                f'height="{sheet_height}" '
                f'class="SHEET" '
                f'{sheet_style} />'
            )
        )

    svg_lines.append('  <g id="NestedSheet">')

    # Nesting geometrileri
    for placement in placements:
        offset_x = placement.x
        offset_y = placement.y
        rotated = bool(placement.rotated)

        for line in pattern.lines:
            if line.layer not in (
                LAYER_CUT,
                LAYER_FOLD,
                LAYER_MARK,
            ):
                continue

            p1 = line.p1
            p2 = line.p2

            # 90° dönüş
            if rotated:
                p1 = (
                    p1[1],
                    pattern_width - p1[0],
                )
                p2 = (
                    p2[1],
                    pattern_width - p2[0],
                )

            # Offset
            transformed_p1 = (
                p1[0] + offset_x,
                p1[1] + offset_y,
            )
            transformed_p2 = (
                p2[0] + offset_x,
                p2[1] + offset_y,
            )

            style_attr = _SVG_INLINE_STYLES.get(line.layer, "")

            svg_lines.append(
                (
                    f'    <line '
                    f'x1="{round(transformed_p1[0], 4)}" '
                    f'y1="{round(sheet_height - transformed_p1[1], 4)}" '
                    f'x2="{round(transformed_p2[0], 4)}" '
                    f'y2="{round(sheet_height - transformed_p2[1], 4)}" '
                    f'class="{line.layer}" '
                    f'{style_attr} />'
                )
            )

    svg_lines.append("  </g>")
    svg_lines.append("</svg>")

    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write("\n".join(svg_lines))

    return str(output_path)