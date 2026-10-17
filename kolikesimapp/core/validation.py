"""
Doğrulama motoru / Validation engine

DXF oluşturulmadan önce ve genel proje durumunda çalışan deterministik
kontroller. Yapay zeka kullanılmaz - sadece kural tabanlı kontroller.
"""

from dataclasses import dataclass
from typing import List

from .models import Project
from .geometry import FlatPattern
from .nesting import NestingResult

LEVEL_OK = "OK"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"


@dataclass
class CheckResult:
    level: str
    message: str


def validate_project(project: Project) -> List[CheckResult]:
    """Genel proje verisi üzerinde temel doğrulamalar yapar."""
    results: List[CheckResult] = []

    def ok(msg):
        results.append(CheckResult(LEVEL_OK, msg))

    def warn(msg):
        results.append(CheckResult(LEVEL_WARN, msg))

    def err(msg):
        results.append(CheckResult(LEVEL_ERROR, msg))

    if project.design_mode == "product_to_box":
        p = project.product
        if not p.validate():
            err("Ürün ölçüleri geçersiz / Invalid product dimensions")
        else:
            ok("Ürün ölçüleri geçerli / Product dimensions valid")

        layout = project.layout
        if not layout.validate():
            err("Dizilim (X/Y/Z) en az 1 olmalı / Layout counts must be >= 1")
        else:
            ok(f"Dizilim geçerli: {layout.total} ürün / Layout valid: {layout.total} products")

    if not project.tolerance.validate():
        err("Tolerans değerleri negatif olamaz / Tolerance values cannot be negative")
    else:
        ok("Tolerans geçerli / Tolerance valid")

    if not project.box.validate():
        err("Koli ölçüsü/tipi geçersiz / Invalid box dimensions or type")
    else:
        ok("Koli ölçüsü geçerli / Box dimensions valid")

    if not project.material.validate():
        err("Malzeme kalınlığı girilmedi / Material thickness missing")
    else:
        ok("Malzeme bilgisi geçerli / Material info valid")

    if not project.sheet.validate():
        err("Levha ölçüsü geçersiz / Invalid sheet dimensions")
    else:
        ok("Levha ölçüsü geçerli / Sheet dimensions valid")

    if not project.laser.validate():
        warn("Lazer türü veya gücü eksik / Laser type or power missing")
    else:
        ok("Lazer bilgisi geçerli / Laser info valid")

    return results


def validate_flat_pattern_fits_sheet(
    pattern: FlatPattern, sheet_width: float, sheet_height: float, margin: float
) -> List[CheckResult]:
    """Tek bir açınımın (rotasyonla birlikte) levhaya sığıp sığmadığını kontrol eder."""
    results: List[CheckResult] = []
    usable_w = sheet_width - 2 * margin
    usable_h = sheet_height - 2 * margin

    fits_normal = pattern.width <= usable_w and pattern.height <= usable_h
    fits_rotated = pattern.height <= usable_w and pattern.width <= usable_h

    if fits_normal:
        results.append(CheckResult(LEVEL_OK, "Açınım levhaya sığıyor / Pattern fits sheet"))
    elif fits_rotated:
        results.append(
            CheckResult(
                LEVEL_WARN,
                "Açınım yalnızca 90° döndürülünce levhaya sığıyor / "
                "Pattern fits sheet only when rotated 90°",
            )
        )
    else:
        over_w = max(0.0, pattern.width - usable_w)
        over_h = max(0.0, pattern.height - usable_h)
        results.append(
            CheckResult(
                LEVEL_ERROR,
                f"HATA: Koli açınımı levha ölçüsünü aşıyor "
                f"(genişlik +{over_w:.1f} mm, yükseklik +{over_h:.1f} mm). "
                f"Çözüm: Daha büyük levha seçin, koli ölçüsünü küçültün "
                f"veya koli tipini değiştirin. / "
                f"ERROR: Flat pattern exceeds sheet size "
                f"(width +{over_w:.1f} mm, height +{over_h:.1f} mm).",
            )
        )
    return results


def check_zero_length_and_duplicate_lines(pattern: FlatPattern) -> List[CheckResult]:
    """Sıfır uzunluklu ve tam çakışan (yinelenen) çizgileri kontrol eder."""
    results: List[CheckResult] = []
    zero_len = 0
    seen = set()
    duplicates = 0

    for ln in pattern.lines:
        if ln.p1 == ln.p2:
            zero_len += 1
            continue
        key = tuple(sorted([ln.p1, ln.p2])) + (ln.layer,)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)

    if zero_len:
        results.append(CheckResult(LEVEL_ERROR, f"{zero_len} adet sıfır uzunluklu çizgi bulundu / {zero_len} zero-length line(s) found"))
    else:
        results.append(CheckResult(LEVEL_OK, "Sıfır uzunluklu çizgi yok / No zero-length lines"))

    if duplicates:
        results.append(CheckResult(LEVEL_WARN, f"{duplicates} adet çift/çakışan çizgi bulundu / {duplicates} duplicate line(s) found"))
    else:
        results.append(CheckResult(LEVEL_OK, "Çift çizgi yok / No duplicate lines"))

    return results


def check_overlaps(nesting_result: NestingResult) -> List[CheckResult]:
    """Nesting sonucundaki dikdörtgen yerleşimlerin birbiriyle çakışmadığını doğrular.

    Grid tabanlı yerleştirme yapısal olarak çakışmayı engeller; bu fonksiyon
    yine de programatik bir güvence (sanity check) sağlar.
    """
    placements = nesting_result.placements
    pw, ph = nesting_result.piece_width, nesting_result.piece_height

    for i in range(len(placements)):
        a = placements[i]
        for j in range(i + 1, len(placements)):
            b = placements[j]
            separated = (
                a.x + pw <= b.x or b.x + pw <= a.x or a.y + ph <= b.y or b.y + ph <= a.y
            )
            if not separated:
                return [CheckResult(LEVEL_ERROR, "Çakışan koli tespit edildi / Overlapping box detected")]

    return [CheckResult(LEVEL_OK, "Çakışma yok / No overlaps")]


def check_sheet_bounds(nesting_result: NestingResult, sheet_width: float, sheet_height: float, margin: float) -> List[CheckResult]:
    """Her yerleşimin levha sınırları içinde kaldığını kontrol eder."""
    pw, ph = nesting_result.piece_width, nesting_result.piece_height
    for p in nesting_result.placements:
        if p.x < margin - 1e-6 or p.y < margin - 1e-6:
            return [CheckResult(LEVEL_ERROR, "Yerleşim levha kenar boşluğunun dışına taşıyor / Placement outside margin")]
        if p.x + pw > sheet_width - margin + 1e-6 or p.y + ph > sheet_height - margin + 1e-6:
            return [CheckResult(LEVEL_ERROR, "Yerleşim levha dışına taşıyor / Placement exceeds sheet bounds")]
    return [CheckResult(LEVEL_OK, "Tüm yerleşimler levha sınırları içinde / All placements within sheet bounds")]


def has_errors(results: List[CheckResult]) -> bool:
    return any(r.level == LEVEL_ERROR for r in results)
