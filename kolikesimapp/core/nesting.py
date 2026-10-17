"""
Nesting motoru / Nesting engine

Tek levha üzerine, aynı koli açınımından mümkün olduğunca fazla sayıda
verimli şekilde yerleştirir. Deterministik bir grid (satır/sütun) algoritması
kullanılır; iki yönelim (0 derece / 90 derece döndürülmüş) karşılaştırılıp
daha fazla parça sığdıran seçilir.

Bu, endüstriyel "irregular nesting" algoritmalarının basitleştirilmiş bir
sürümüdür ancak çakışmasız ve levha sınırları içinde kalacak şekilde
matematiksel olarak garanti eder.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

from .models import Sheet


@dataclass
class Placement:
    x: float
    y: float
    rotated: bool


@dataclass
class NestingResult:
    placements: List[Placement] = field(default_factory=list)
    count: int = 0
    sheet_area: float = 0.0
    used_area: float = 0.0
    # ÖNEMLİ - bu alanın anlamı: açınımın GERÇEK (delikli/çentikli) kesim
    # alanı değil, parçanın dikdörtgen SINIRLAYICI KUTUSUNUN (bounding box)
    # levhadaki boş kalan oranıdır. Gerçek lazer/bıçak firesi (malzeme
    # kaybı), parça şeklinin köşe boşlukları, levha kenar payı, parçalar
    # arası kesim toleransı gibi etkenlerle bundan FARKLI olur - genelde
    # daha düşüktür, çünkü iki bitişik parçanın girinti/çıkıntıları
    # birbirine kenetlenebilir. Bu değeri "gerçek üretim firesi" olarak
    # değil, kaba bir yerleşim-verimliliği tahmini olarak kullanın.
    waste_percent: float = 100.0
    piece_width: float = 0.0   # yerleştirilen parçanın (döndürülmüş olabilir) genişliği
    piece_height: float = 0.0


def _grid_count(
    sheet_w: float, sheet_h: float, piece_w: float, piece_h: float, spacing: float, margin: float
) -> Tuple[int, int]:
    usable_w = sheet_w - 2 * margin
    usable_h = sheet_h - 2 * margin
    if piece_w <= 0 or piece_h <= 0 or usable_w <= 0 or usable_h <= 0:
        return 0, 0
    cols = int((usable_w + spacing) // (piece_w + spacing))
    rows = int((usable_h + spacing) // (piece_h + spacing))
    return max(cols, 0), max(rows, 0)


def nest_single_pattern(piece_width: float, piece_height: float, sheet: Sheet) -> NestingResult:
    """Tek bir açınım tipini (aynı koli) tek levhaya grid mantığıyla yerleştirir."""

    margin, spacing = sheet.margin, sheet.spacing

    cols_normal, rows_normal = _grid_count(
        sheet.width, sheet.height, piece_width, piece_height, spacing, margin
    )
    count_normal = cols_normal * rows_normal

    cols_rot, rows_rot = _grid_count(
        sheet.width, sheet.height, piece_height, piece_width, spacing, margin
    )
    count_rot = cols_rot * rows_rot

    if count_rot > count_normal:
        cols, rows, rotated = cols_rot, rows_rot, True
        pw, ph = piece_height, piece_width
        count = count_rot
    else:
        cols, rows, rotated = cols_normal, rows_normal, False
        pw, ph = piece_width, piece_height
        count = count_normal

    placements: List[Placement] = []
    for r in range(rows):
        for c in range(cols):
            x = margin + c * (pw + spacing)
            y = margin + r * (ph + spacing)
            placements.append(Placement(x=x, y=y, rotated=rotated))

    sheet_area = sheet.width * sheet.height
    used_area = count * (piece_width * piece_height)
    waste_percent = 100.0 if sheet_area == 0 else round(100.0 * (1 - used_area / sheet_area), 2)

    return NestingResult(
        placements=placements,
        count=count,
        sheet_area=round(sheet_area, 2),
        used_area=round(used_area, 2),
        waste_percent=waste_percent,
        piece_width=pw,
        piece_height=ph,
    )
