"""
KoliKesimApp - Polygon Based 2D Packaging Geometry Engine (Professional Refactor)

Bu motor, panel geometrisini Shapely polygonlarıyla ifade eder; kesim (CUT)
konturları ve komşu panellerin ortak sınırlarından otomatik türetilen katlama
(FOLD) çizgileri, boolean (union/difference) işlemleriyle hesaplanır. Bu
sayede elle çizgi çizmekten kaynaklanan hizalama/örtüşme hataları büyük
ölçüde elenir.

Desteklenen FEFCO tipleri (bkz. models.BOX_TYPES):
    0200  Kapaksız basit gövde (ekonomik, üst/alt kapak yok)
    0201  RSC (Regular Slotted Container) - standart, en yaygın kullanılan
    0202  Kısmi bindirmeli koli
    0203  Tam bindirmeli koli (FOL - Full Overlap Container)
    0301  Teleskopik kutu (ayrı taban + kapak)
    0422  Kendinden kilitli tepsi (dilli/yuvalı, yapıştırıcısız)
    0427  Kendinden kilitli kargo kutusu (kilit kulaklı / ear-lock)
    custom  Özel parametrik koli (0201 tabanlı)

ÖNEMLİ - FEFCO kod notu: "Tam bindirme" (full overlap) kolinin doğru FEFCO
kodu 0203'tür. Bazı kaynaklarda / önceki sürümlerde bu yanlışlıkla 0210 ile
karıştırılmıştır; 0210 farklı bir alt varyanttır ve burada kullanılmamaktadır.

Tüm geometri deterministiktir. AI kullanılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Tuple, Dict, Optional

from shapely import set_precision
from shapely.affinity import translate
from shapely.geometry import (
    Polygon,
    MultiPolygon,
    LineString,
    MultiLineString,
    GeometryCollection,
)
from shapely.ops import unary_union
from shapely.validation import make_valid

from .models import (
    Product,
    Layout,
    Tolerance,
    BoxParams,
    Material,
)

Point = Tuple[float, float]

LAYER_CUT = "CUT"
LAYER_FOLD = "FOLD"
LAYER_MARK = "MARK"

SNAP_GRID = 0.05
LINE_EPSILON = 0.001
CREASE_COEFFICIENT = 0.5
SLOT_FACTOR = 0.85

# Bitişik iki kapak/kulak (flap), aynı panel sınırında tam olarak birbirine
# değerse, Shapely bu ortak kenarı "paylaşılan sınır" (=FOLD/katlama) olarak
# algılar. Ama gerçekte bu iki kapak birbirinden BAĞIMSIZ yönlere katlanır
# (örn. bir Yan panel kapağı kutunun L yönüne, bitişik Ön panel kapağı W
# yönüne katlanır) - bu yüzden aralarında MUTLAKA gerçek bir KESİM (slot)
# olmalı, aksi halde lazer o köşeyi kesmez ve kapaklar birbirine yapışık
# kalır. Bu küçük pay, kapakları paneliyle aynı hizada (görsel olarak temiz)
# tutarken, bitişik kapaklar arasında gerçek bir kesim garanti eder.
FLAP_SLOT_GAP = 1.0


@dataclass(frozen=True)
class Line:
    p1: Point
    p2: Point
    layer: str = LAYER_CUT

    @property
    def length(self) -> float:
        dx = self.p2[0] - self.p1[0]
        dy = self.p2[1] - self.p1[1]
        return (dx * dx + dy * dy) ** 0.5


@dataclass
class FlatPattern:
    lines: List[Line] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    box_type: str = "0201"
    polygons: List[Polygon] = field(default_factory=list)
    mark_lines: List[Line] = field(default_factory=list)

    def bounds(self) -> Tuple[float, float, float, float]:
        if self.polygons:
            geometry = _safe_union(self.polygons)
            if not geometry.is_empty:
                return geometry.bounds
        if not self.lines:
            return (0.0, 0.0, 0.0, 0.0)

        xs = [line.p1[0] for line in self.lines] + [line.p2[0] for line in self.lines]
        ys = [line.p1[1] for line in self.lines] + [line.p2[1] for line in self.lines]
        return (min(xs), min(ys), max(xs), max(ys))

    def normalize(self) -> "FlatPattern":
        min_x, min_y, max_x, max_y = self.bounds()
        offset_x = -min_x
        offset_y = -min_y

        normalized_polygons = [
            translate(polygon, xoff=offset_x, yoff=offset_y)
            for polygon in self.polygons
        ]

        normalized_lines = [
            Line((line.p1[0] + offset_x, line.p1[1] + offset_y),
                 (line.p2[0] + offset_x, line.p2[1] + offset_y), line.layer)
            for line in self.lines
        ]

        normalized_marks = [
            Line((line.p1[0] + offset_x, line.p1[1] + offset_y),
                 (line.p2[0] + offset_x, line.p2[1] + offset_y), line.layer)
            for line in self.mark_lines
        ]

        result = FlatPattern(
            lines=optimize_lines(normalized_lines),
            width=max_x - min_x,
            height=max_y - min_y,
            box_type=self.box_type,
            polygons=normalized_polygons,
            mark_lines=optimize_lines(normalized_marks),
        )
        result.update_dimensions()
        return result

    def update_dimensions(self) -> None:
        min_x, min_y, max_x, max_y = self.bounds()
        self.width = max(0.0, max_x - min_x)
        self.height = max(0.0, max_y - min_y)

    def line_count_by_layer(self) -> Dict[str, int]:
        counts = {LAYER_CUT: 0, LAYER_FOLD: 0, LAYER_MARK: 0}
        for line in self.lines:
            counts[line.layer] = counts.get(line.layer, 0) + 1
        return counts


def _snap_value(value: float, grid: float = SNAP_GRID) -> float:
    if grid <= 0:
        return float(value)
    return round(value / grid) * grid


def _snap_point(point: Point, grid: float = SNAP_GRID) -> Point:
    return (_snap_value(point[0], grid), _snap_value(point[1], grid))


def _snap_lines(lines: Iterable[Line]) -> List[Line]:
    return [
        Line(p1=_snap_point(line.p1), p2=_snap_point(line.p2), layer=line.layer)
        for line in lines
    ]


def _line_key(line: Line):
    p1 = _snap_point(line.p1)
    p2 = _snap_point(line.p2)
    ordered = sorted((p1, p2))
    return (ordered[0], ordered[1], line.layer)


def optimize_lines(lines: Iterable[Line]) -> List[Line]:
    snapped = _snap_lines(lines)
    unique = []
    seen = set()
    for line in snapped:
        if line.length <= LINE_EPSILON:
            continue
        key = _line_key(line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _clamp(value: float, lo: float, hi: float) -> float:
    hi = max(hi, lo)
    return max(lo, min(hi, value))


def _safe_polygon(geometry):
    if geometry is None or geometry.is_empty:
        return None
    geometry = set_precision(geometry, SNAP_GRID)
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    return geometry if not geometry.is_empty else None


def _safe_union(polygons: Iterable):
    geometries = [p for p in polygons if p is not None and not p.is_empty]
    if not geometries:
        return GeometryCollection()
    geometry = unary_union(geometries)
    geometry = _safe_polygon(geometry)
    return geometry if geometry is not None else GeometryCollection()


def _polygon_rectangle(x: float, y: float, width: float, height: float) -> Polygon:
    if width <= 0 or height <= 0:
        raise ValueError("Polygon boyutları pozitif olmalıdır.")
    return _safe_polygon(Polygon([(x, y), (x + width, y), (x + width, y + height), (x, y + height)]))


def _polygon_flap(left: float, right: float, hinge_y: float, direction: int, depth: float) -> Polygon:
    if right <= left or depth <= 0:
        raise ValueError("Flap ölçüleri geçersiz.")
    outer_y = hinge_y + direction * depth
    return _safe_polygon(Polygon([(left, hinge_y), (right, hinge_y), (right, outer_y), (left, outer_y)]))


def _polygon_flap_with_tab(left: float, right: float, hinge_y: float, direction: int,
                           depth: float, tab_width: float, tab_depth: float) -> Polygon:
    """Ortasında dışa doğru küçük bir kilit dili (tab) çıkıntısı olan bir kapak.

    Ana dikdörtgen kapak + onun dış kenarından uzanan daha küçük bir dil
    dikdörtgeni birleştirilerek (union) tek bir polygon olarak döndürülür.
    """
    main = _polygon_flap(left, right, hinge_y, direction, depth)

    tab_width = max(0.0, min(tab_width, (right - left) * 0.8))
    if tab_width <= 0 or tab_depth <= 0:
        return main

    outer_y = hinge_y + direction * depth
    tab_outer_y = outer_y + direction * tab_depth
    mid = (left + right) / 2.0
    tab_l, tab_r = mid - tab_width / 2.0, mid + tab_width / 2.0

    tab = _polygon_rectangle(tab_l, min(outer_y, tab_outer_y), tab_width, abs(tab_outer_y - outer_y))
    merged = _safe_union([main, tab])
    return merged if merged is not None else main


def _polygon_chamfered_glue_flap(width: float, bottom: float, top: float, chamfer: float) -> Polygon:
    """Yapıştırma kulağı (glue flap): sivri uçlu + kısa omuz basamaklı şekil.

    Profesyonel dieline şablonlarında (ör. Pacdora) yaygın görülen glue-flap
    görünümüne yakın: dar/sivri bir burun, ardından kısa bir omuz basamağı
    ile tam panel yüksekliğine açılır (yapıştırma sırasında hizalamayı
    kolaylaştıran bir tasarım detayı).
    """
    height = top - bottom
    chamfer = max(0.0, min(chamfer, height / 2.0))
    shoulder = min(width * 0.35, chamfer * 0.8)
    nose_x = max(0.0, width - shoulder - max(width - shoulder, 0.1))
    mid = (top + bottom) / 2.0

    if chamfer <= 0.5 or shoulder <= 0.5:
        points = [(0.0, bottom + chamfer), (0.0, top - chamfer), (width, top), (width, bottom)]
    else:
        points = [
            (0.0, mid),                          # sivri burun ucu
            (shoulder, top - chamfer),            # üst diagonal -> omuz
            (shoulder, top),                      # omuz -> tam yükseklik
            (width, top),
            (width, bottom),
            (shoulder, bottom),                   # tam yükseklik -> omuz
            (shoulder, bottom + chamfer),          # omuz -> alt diagonal
        ]
    return _safe_polygon(Polygon(points))


def _extract_lines(geometry) -> List[LineString]:
    result: List[LineString] = []

    if geometry is None or geometry.is_empty:
        return result
    if isinstance(geometry, LineString):
        if geometry.length > LINE_EPSILON:
            result.append(geometry)
        return result
    if isinstance(geometry, MultiLineString):
        for part in geometry.geoms:
            result.extend(_extract_lines(part))
        return result
    if isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            result.extend(_extract_lines(part))
        return result
    return result


def _linestring_to_segments(line_string: LineString, layer: str) -> List[Line]:
    coords = list(line_string.coords)
    return [
        Line(p1=(float(p1[0]), float(p1[1])), p2=(float(p2[0]), float(p2[1])), layer=layer)
        for p1, p2 in zip(coords[:-1], coords[1:])
    ]


def _ring_to_lines(ring, layer: str) -> List[Line]:
    coords = list(ring.coords)
    return [
        Line(p1=(float(p1[0]), float(p1[1])), p2=(float(p2[0]), float(p2[1])), layer=layer)
        for p1, p2 in zip(coords[:-1], coords[1:])
    ]


def _geometry_boundaries_to_cut(geometry) -> List[Line]:
    result = []
    if geometry.is_empty:
        return result
    if isinstance(geometry, Polygon):
        result.extend(_ring_to_lines(geometry.exterior, LAYER_CUT))
        for interior in geometry.interiors:
            result.extend(_ring_to_lines(interior, LAYER_CUT))
        return result
    if isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            result.extend(_geometry_boundaries_to_cut(polygon))
        return result
    return result


def _shared_boundaries_to_fold(polygons: List[Polygon]) -> List[Line]:
    fold_lines: List[Line] = []
    for i in range(len(polygons)):
        polygon_a = polygons[i]
        if polygon_a is None:
            continue
        boundary_a = polygon_a.boundary
        for j in range(i + 1, len(polygons)):
            polygon_b = polygons[j]
            if polygon_b is None:
                continue
            boundary_b = polygon_b.boundary
            intersection = boundary_a.intersection(boundary_b)
            for line_string in _extract_lines(intersection):
                fold_lines.extend(_linestring_to_segments(line_string, LAYER_FOLD))
    return optimize_lines(fold_lines)


def _build_flat_pattern(polygons: List[Polygon], box_type: str, mark_lines: Optional[List[Line]] = None, difference_geometry=None) -> FlatPattern:
    cleaned_polygons = [p for p in (_safe_polygon(poly) for poly in polygons) if p is not None]
    if not cleaned_polygons:
        raise ValueError("Flat pattern için hiç polygon oluşturulmadı.")

    folds = _shared_boundaries_to_fold(cleaned_polygons)
    union_geometry = _safe_union(cleaned_polygons)

    if difference_geometry is not None and not difference_geometry.is_empty:
        difference_geometry = _safe_polygon(difference_geometry)
        union_geometry = union_geometry.difference(difference_geometry)
        union_geometry = _safe_polygon(union_geometry)

    if union_geometry is None:
        raise ValueError("Boolean geometri sonucu boş.")

    cuts = _geometry_boundaries_to_cut(union_geometry)
    marks = mark_lines if mark_lines else []
    all_lines = optimize_lines(cuts + folds + marks)

    pattern = FlatPattern(
        lines=all_lines,
        box_type=box_type,
        polygons=cleaned_polygons,
        mark_lines=optimize_lines(marks),
    )
    pattern.update_dimensions()
    return pattern.normalize()


def _flat_dimension(inner_dimension: float, material_thickness: float, coefficient: float = CREASE_COEFFICIENT) -> float:
    return float(inner_dimension) + coefficient * float(material_thickness)


def compute_internal_box_dimensions(product: Product, layout: Layout, tolerance: Tolerance):
    product_x = product.width if product.rotation not in (90, 270) else product.depth
    product_y = product.depth if product.rotation not in (90, 270) else product.width

    length = layout.x_count * product_x + (layout.x_count - 1) * tolerance.gap_x + 2 * tolerance.wall_x
    width = layout.y_count * product_y + (layout.y_count - 1) * tolerance.gap_y + 2 * tolerance.wall_y
    height = layout.z_count * product.height + (layout.z_count - 1) * tolerance.gap_z + 2 * tolerance.wall_z
    return (round(length, 2), round(width, 2), round(height, 2))


def compute_product_positions(product: Product, layout: Layout, tolerance: Tolerance):
    product_x = product.width if product.rotation not in (90, 270) else product.depth
    product_y = product.depth if product.rotation not in (90, 270) else product.width

    positions = []
    for z in range(max(1, layout.z_count)):
        z_position = tolerance.wall_z + z * (product.height + tolerance.gap_z)
        for y in range(max(1, layout.y_count)):
            y_position = tolerance.wall_y + y * (product_y + tolerance.gap_y)
            for x in range(max(1, layout.x_count)):
                x_position = tolerance.wall_x + x * (product_x + tolerance.gap_x)
                positions.append((round(x_position, 2), round(y_position, 2), round(z_position, 2)))
    return positions


def _calculate_glue_flap_width(material_thickness: float) -> float:
    t = max(float(material_thickness), 0.01)
    if t <= 3.0: return 30.0
    elif t <= 5.0: return 35.0
    else: return 40.0


# ============================================================================
# Paylaşılan yardımcı: major/minor kapak derinlikleri (02-serisi slotlu kutular)
# ============================================================================
#
# KRİTİK GEOMETRİ NOTU: panel sırası her zaman (Yan1, Ön, Yan2, Arka) =
# (W, L, W, L) şeklindedir. Yan panellerin (menteşe uzunluğu = W) kapakları,
# katlandığında kutunun L (uzunluk) yönünde açılır - bu yüzden derinlikleri
# L'ye bağlı olmalıdır. Ön/Arka panellerin (menteşe uzunluğu = L) kapakları
# ise W (genişlik) yönünde açılır - derinlikleri W'ye bağlı olmalıdır.
#
# Önceki bir sürümde bu iki yön birbirine karıştırılmış (her iki kapak tipi
# de yalnızca W kullanılarak hesaplanmış), bu da L, W'den belirgin şekilde
# büyük olan (çoğu gerçek koli böyledir) kutularda üst/alt yüzeyin ortasında,
# L boyunca uzanan dikdörtgen bir BOŞLUK bırakıyordu - yani kutu fiziksel
# olarak tam kapanmıyordu. Bu fonksiyon, doğru eksen eşlemesini TEK bir
# yerden garanti eder; tüm 02-serisi üreticiler (0201/0202/0203) buradan
# beslenir.
def _rsc_flap_depths(flat_L: float, flat_W: float, t: float, clearance: float,
                      overlap: float = 0.0, full_overlap: bool = False) -> Tuple[float, float]:
    """Ön/Arka (major, W-tabanlı) ve Yan (minor, L-tabanlı) kapak derinliklerini döndürür."""
    if full_overlap:
        # 0203 - neredeyse W'nin tamamı kadar (çift katmanlı üst/alt yüzey)
        major_depth = max(flat_W - t * 2.0 - 5.0, flat_W / 2.0)
    else:
        # 0201 (overlap=0) veya 0202 (overlap>0, kısmi bindirme)
        major_depth = max(flat_W / 2.0 - t * 0.5 + overlap, t)

    # Yan panel kapakları L yönünde uzanır; ortada buluşmamaları için
    # `clearance` kadar kısaltılır (major kapakların altında kalırlar).
    minor_depth = max(flat_L / 2.0 - clearance / 2.0, t)

    return major_depth, minor_depth


def _generate_slotted_box(box: BoxParams, material: Material, box_type: str,
                           overlap: float = 0.0, full_overlap: bool = False) -> FlatPattern:
    """02-serisi (RSC ailesi) slotlu kutuların ortak gövde + kapak inşası."""
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)
    flat_L, flat_W, flat_H = _flat_dimension(L, t), _flat_dimension(W, t), _flat_dimension(H, t)

    glue_flap = _calculate_glue_flap_width(t)
    clearance = max(float(box.minor_flap_clearance), t)
    major_depth, minor_depth = _rsc_flap_depths(flat_L, flat_W, t, clearance, overlap=overlap, full_overlap=full_overlap)

    polygons = []
    chamfer = min(15.0, glue_flap * 0.4, flat_H * 0.25)
    polygons.append(_polygon_chamfered_glue_flap(glue_flap, 0.0, flat_H, chamfer))

    current_x = glue_flap
    for panel_width in (flat_W, flat_L, flat_W, flat_L):
        polygons.append(_polygon_rectangle(current_x, 0.0, panel_width, flat_H))
        current_x += panel_width

    current_x = glue_flap
    for index, panel_width in enumerate((flat_W, flat_L, flat_W, flat_L)):
        # Kapak genişliği panel genişliğiyle aynı hizada kalır (görsel
        # temizlik); yalnızca bitişik bir kapak varsa (ilk/son panel
        # hariç) o kenara küçük bir FLAP_SLOT_GAP payı bırakılır - bu,
        # lazerin bitişik kapakları birbirinden gerçekten AYIRMASINI
        # (kesmesini) garanti eder (bkz. FLAP_SLOT_GAP tanımı).
        left = current_x + (FLAP_SLOT_GAP / 2.0 if index > 0 else 0.0)
        right = current_x + panel_width - (FLAP_SLOT_GAP / 2.0 if index < 3 else 0.0)
        # index 0,2 -> Yan paneller (W menteşeli) -> minor (L-tabanlı) kapak
        # index 1,3 -> Ön/Arka paneller (L menteşeli) -> major (W-tabanlı) kapak
        depth = minor_depth if index in (0, 2) else major_depth
        polygons.append(_polygon_flap(left, right, 0.0, -1, depth))
        polygons.append(_polygon_flap(left, right, flat_H, +1, depth))
        current_x += panel_width

    return _build_flat_pattern(polygons, box_type)


# ============================================================================
# 0. FEFCO 0200: Kapaksız Basit Gövde (üst/alt kapak yok, ekonomik tepsi/manşon)
# ============================================================================
def generate_fefco_0200_pattern(box: BoxParams, material: Material) -> FlatPattern:
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)
    flat_L, flat_W, flat_H = _flat_dimension(L, t), _flat_dimension(W, t), _flat_dimension(H, t)

    glue_flap = _calculate_glue_flap_width(t)
    polygons = []

    chamfer = min(15.0, glue_flap * 0.4, flat_H * 0.25)
    polygons.append(_polygon_chamfered_glue_flap(glue_flap, 0.0, flat_H, chamfer))

    current_x = glue_flap
    for panel_width in (flat_W, flat_L, flat_W, flat_L):
        polygons.append(_polygon_rectangle(current_x, 0.0, panel_width, flat_H))
        current_x += panel_width

    return _build_flat_pattern(polygons, "0200")


# ============================================================================
# 1. FEFCO 0201: Standart RSC Koli (Kapaklar ortada birleşir)
# ============================================================================
def generate_fefco_0201_pattern(box: BoxParams, material: Material) -> FlatPattern:
    return _generate_slotted_box(box, material, "0201")


# ============================================================================
# 2. FEFCO 0202: Kısmi Bindirmeli Koli (major kapaklar W/2'nin biraz ötesine uzanır)
# ============================================================================
def generate_fefco_0202_pattern(box: BoxParams, material: Material) -> FlatPattern:
    W = float(box.width)
    t = max(float(material.thickness), 0.01)
    flat_W = _flat_dimension(W, t)
    overlap_extra = min(50.0, flat_W * 0.2)   # tipik ~25-50mm ek bindirme payı
    return _generate_slotted_box(box, material, "0202", overlap=overlap_extra)


# ============================================================================
# 3. FEFCO 0203: Tam Bindirmeli Koli (FOL - Full Overlap Container)
# ============================================================================
def generate_fefco_0203_pattern(box: BoxParams, material: Material) -> FlatPattern:
    return _generate_slotted_box(box, material, "0203", full_overlap=True)


# ============================================================================
# 4. FEFCO 0301 / 0217: Teleskopik Kutu (Ayrı Taban Gövde + Ayrı Kapak)
# ============================================================================
#
# İkisi de aynı mekanizmayı kullanır (taban + üzerine oturan ayrı kapak);
# fark yalnızca kapağın derinliğidir:
#   - 0301: sığ kapak (kutu kapağı / shoe-box tarzı), lid_depth_ratio küçük
#   - 0217: derin kapak (arşiv/depolama kutusu, kapak yüksekliğin büyük
#     kısmını kaplar), lid_depth_ratio büyük
def _generate_telescope_box(box: BoxParams, material: Material, box_type: str, lid_depth_ratio: float) -> FlatPattern:
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)
    flat_L, flat_W = _flat_dimension(L, t), _flat_dimension(W, t)

    skirt = max(20.0, t * 5.0, H * lid_depth_ratio)

    base = generate_fefco_0201_pattern(box, material)
    polygons = list(base.polygons)

    lid_offset_x = base.width + 30.0
    lid_W = flat_W + t * 2.0
    lid_L = flat_L + t * 2.0

    center_lid = _polygon_rectangle(lid_offset_x + skirt, skirt, lid_L, lid_W)
    polygons.append(center_lid)

    polygons.append(_polygon_flap(lid_offset_x + skirt, lid_offset_x + skirt + lid_L, skirt, -1, skirt))
    polygons.append(_polygon_flap(lid_offset_x + skirt, lid_offset_x + skirt + lid_L, skirt + lid_W, +1, skirt))

    return _build_flat_pattern(polygons, box_type)


def generate_fefco_0301_pattern(box: BoxParams, material: Material) -> FlatPattern:
    """FEFCO 0301: Sığ kapak - kutu kapağı / hediye kutusu tarzı teleskopik kutu."""
    return _generate_telescope_box(box, material, "0301", lid_depth_ratio=0.15)


def generate_fefco_0217_pattern(box: BoxParams, material: Material) -> FlatPattern:
    """FEFCO 0217: Derin kapak - arşiv/depolama kutusu tarzı teleskopik kutu.

    Kapak, kutu yüksekliğinin büyük kısmını (~%75) kaplayacak şekilde
    derinleştirilir - taşıma sırasında içeriğin kapaktan görünmesini/
    dökülmesini engeller, arşiv ve depolama kutularında tercih edilir.
    """
    return _generate_telescope_box(box, material, "0217", lid_depth_ratio=0.75)


# ============================================================================
# 4b. FEFCO 0713: Crash-Lock (Kilitlemeli) Otomatik Taban + Kilit Dilli Üst Kapak
# ============================================================================
#
# Yüksek hacimli e-ticaret/fulfillment hatlarının favorisi: taban,
# yapıştırıcı/bant gerektirmeden tek harekette kurulur. Gövde RSC ile aynı
# 4 duvar iskeletini kullanır (Yan1-Ön-Yan2-Arka). Taban: Yan panellerden
# düz (minor, L-tabanlı) kapaklar + Ön panelden çıkan bir "dil" (tongue) +
# Arka panelin kapağına açılan karşılık gelen bir yuva (slot) - dil yuvaya
# geçerek tabanı bantsız kilitler. Üst kapak: standart kilit dilli tuck-top
# (Arka panelden) + iki toz kapağı (Yan panellerden).
#
# Not: Gerçek üretimdeki çapraz "dokuma" (weave) crash-lock mekanizmasının
# basitleştirilmiş, dil+yuva tabanlı bir yorumudur; üretim öncesi test
# kesimiyle doğrulanmalıdır.
def generate_fefco_0713_pattern(box: BoxParams, material: Material) -> FlatPattern:
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)
    flat_L, flat_W, flat_H = _flat_dimension(L, t), _flat_dimension(W, t), _flat_dimension(H, t)

    glue_flap = _calculate_glue_flap_width(t)
    clearance = max(float(box.minor_flap_clearance), t)
    major_depth, minor_depth = _rsc_flap_depths(flat_L, flat_W, t, clearance)

    tongue_width = min(flat_L * 0.25, 40.0)
    tongue_depth = max(t * 3.0, 8.0)
    slot_inset = max(t * 2.0, 6.0)

    tuck_depth = max(flat_W * 0.55, 25.0)
    lock_tab_width = min(flat_L * 0.3, 25.0)
    lock_tab_depth = max(t * 3.0, 4.0)

    polygons = []
    chamfer = min(15.0, glue_flap * 0.4, flat_H * 0.25)
    polygons.append(_polygon_chamfered_glue_flap(glue_flap, 0.0, flat_H, chamfer))

    current_x = glue_flap
    for panel_width in (flat_W, flat_L, flat_W, flat_L):
        polygons.append(_polygon_rectangle(current_x, 0.0, panel_width, flat_H))
        current_x += panel_width

    x0 = glue_flap
    x1 = x0 + flat_W   # Yan1 sonu
    x2 = x1 + flat_L   # Ön sonu
    x3 = x2 + flat_W   # Yan2 sonu
    x4 = x3 + flat_L   # Arka sonu

    # --- Taban: Yan panellerden düz (minor) kapaklar ---
    g = FLAP_SLOT_GAP / 2.0
    polygons.append(_polygon_flap(x0, x1 - g, 0.0, -1, minor_depth))
    polygons.append(_polygon_flap(x2 + g, x3 - g, 0.0, -1, minor_depth))

    # --- Taban: Ön panelden major kapak + kilit dili (tongue) ---
    front_center = (x1 + x2) / 2.0
    tongue_l = front_center - tongue_width / 2.0
    polygons.append(_polygon_flap(x1 + g, x2 - g, 0.0, -1, major_depth))
    polygons.append(_polygon_rectangle(tongue_l, -(major_depth + tongue_depth), tongue_width, tongue_depth))

    # --- Taban: Arka panelden major kapak + karşılık gelen yuva ---
    back_center = (x3 + x4) / 2.0
    polygons.append(_polygon_flap(x3 + g, x4, 0.0, -1, major_depth))
    slot = _polygon_rectangle(
        back_center - tongue_width / 2.0, -major_depth + slot_inset, tongue_width, tongue_depth,
    )

    # --- Üst kapak: Yan panellerden toz kapakları (minor, dust flap) ---
    polygons.append(_polygon_flap(x0, x1, flat_H, +1, minor_depth))
    polygons.append(_polygon_flap(x2, x3 - g, flat_H, +1, minor_depth))

    # --- Üst kapak: Arka panelden ana kilit kapağı (dilli tuck-top) ---
    tab_w = min(lock_tab_width, (x4 - x3) * 0.6)
    polygons.append(_polygon_flap_with_tab(x3 + g, x4, flat_H, +1, tuck_depth, tab_w, lock_tab_depth))
    # Ön panel açık bırakılır - kilit kapağı buraya oturur.

    marks = [
        Line((x1, flat_H + tuck_depth * 0.5), (x2, flat_H + tuck_depth * 0.5), LAYER_MARK),
    ]

    return _build_flat_pattern(polygons, "0713", mark_lines=marks, difference_geometry=slot)


# ============================================================================
# 5. FEFCO 0422: Kendinden Kilitli Tepsi (Self-Locking Tray)
# ============================================================================
#
# 4 duvar (Yan1-Ön-Yan2-Arka) art arda dizilir; yapıştırma kulağı yerine
# duvarların birleştiği dikişte menteşeli bir kilit dili (tab) ve karşı
# duvarda buna karşılık gelen bir yuva (slot) bulunur - tamamen mekanik,
# yapıştırıcısız birleşim. Taban, standart RSC major/minor kapak mantığıyla
# kapanır (bkz. _rsc_flap_depths); üst kısım açık bırakılır.
def _build_0422_body(box: BoxParams, material: Material):
    """FEFCO 0422 gövdesini (panel + tab + kapak) ve yuva (slot) geometrisini
    AYRI olarak döndürür - böylece bu gövdeyi temel alan diğer tipler
    (0421, display) yuvayı kaybetmeden yeniden kullanabilir.

    _build_flat_pattern, polygonları fark alma (difference) işleminden
    ÖNCEKİ haliyle sakladığı için, yuva gibi bir "difference_geometry" tek
    başına .polygons üzerinden görünmez olur - bu yardımcı fonksiyon bunu
    açıkça (polygons, slot_geometry) olarak dışa verir.
    """
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)
    flat_L, flat_W, flat_H = _flat_dimension(L, t), _flat_dimension(W, t), _flat_dimension(H, t)

    clearance = max(float(box.minor_flap_clearance), t)
    major_depth, minor_depth = _rsc_flap_depths(flat_L, flat_W, t, clearance)

    tab_height = _clamp(flat_H * 0.5, t * 4.0, 25.0)
    tab_protrusion = max(t * 3.0, 6.0)
    slot_inset = max(t * 2.0, 5.0)

    panel_widths = (flat_W, flat_L, flat_W, flat_L)
    total_width = sum(panel_widths)

    polygons = []
    current_x = 0.0
    for panel_width in panel_widths:
        polygons.append(_polygon_rectangle(current_x, 0.0, panel_width, flat_H))
        current_x += panel_width

    tab_center_y = flat_H / 2.0
    tab_bottom = tab_center_y - tab_height / 2.0
    polygons.append(_polygon_rectangle(-tab_protrusion, tab_bottom, tab_protrusion, tab_height))

    slot = _polygon_rectangle(total_width - slot_inset - tab_protrusion, tab_bottom, tab_protrusion, tab_height)

    current_x = 0.0
    kinds = ("side", "front", "side", "back")
    panel_count = len(panel_widths)
    g = FLAP_SLOT_GAP / 2.0
    for i, (kind, panel_width) in enumerate(zip(kinds, panel_widths)):
        left = current_x + (g if i > 0 else 0.0)
        right = current_x + panel_width - (g if i < panel_count - 1 else 0.0)
        depth = minor_depth if kind == "side" else major_depth
        polygons.append(_polygon_flap(left, right, 0.0, -1, depth))
        current_x += panel_width

    return polygons, slot


def generate_fefco_0422_pattern(box: BoxParams, material: Material) -> FlatPattern:
    polygons, slot = _build_0422_body(box, material)
    return _build_flat_pattern(polygons, "0422", difference_geometry=slot)


# ============================================================================
# 6. FEFCO 0427: Kendinden Kilitli Kargo Kutusu (Kilit Kulaklı / Ear-Lock)
# ============================================================================
#
# Tek parça, bantsız/yapıştırıcısız kapanan popüler e-ticaret/kargo kutusu.
# Panel sırası (dikey şerit): Arka - Taban - Ön - Kapak; Taban'ın sol/sağ
# kenarlarından yan duvarlar (H x W) çıkar. Kapağın sol/sağ kenarlarından
# uzanan kilit kulakları (ear tab), yan duvarların ön-üst köşesine açılan
# yuvalara (slot) geçerek kutuyu bantsız kilitler.
#
# Not: Kulak/yuva konumu, gerçek üretim öncesi bir prototiple doğrulanmalı;
# amaç, kendinden kilitleme prensibini doğru ve tutarlı şekilde modellemektir.
def generate_fefco_0427_pattern(box: BoxParams, material: Material) -> FlatPattern:
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)
    flat_L, flat_W, flat_H = _flat_dimension(L, t), _flat_dimension(W, t), _flat_dimension(H, t)

    wall_y = flat_H
    lid_depth = flat_W
    ear_width = _clamp(wall_y * 0.35, 10.0, 30.0)
    ear_depth = max(t * 3.0, 8.0)
    slot_inset = max(t * 2.0, 6.0)

    polygons = []

    base_panel = _polygon_rectangle(0, wall_y, flat_L, flat_W)
    polygons.append(base_panel)

    back_wall = _polygon_rectangle(0, 0, flat_L, wall_y)
    polygons.append(back_wall)

    front_wall = _polygon_rectangle(0, wall_y + flat_W, flat_L, wall_y)
    polygons.append(front_wall)

    lid_panel = _polygon_rectangle(0, wall_y * 2 + flat_W, flat_L, lid_depth)
    polygons.append(lid_panel)

    left_side = _polygon_rectangle(-wall_y, wall_y, wall_y, flat_W)
    right_side = _polygon_rectangle(flat_L, wall_y, wall_y, flat_W)
    polygons.append(left_side)
    polygons.append(right_side)

    # Kapağın serbest (dış) kenarına yakın, sol/sağ kilit kulakları
    lid_outer_y = wall_y * 2 + flat_W + lid_depth
    ear_top = lid_outer_y - slot_inset
    ear_bottom = max(ear_top - ear_width, wall_y * 2 + flat_W)
    ear_width = ear_top - ear_bottom  # sınırlandıysa gerçek değere göre düzelt

    if ear_width > LINE_EPSILON:
        polygons.append(_polygon_rectangle(-ear_depth, ear_bottom, ear_depth, ear_width))
        polygons.append(_polygon_rectangle(flat_L, ear_bottom, ear_depth, ear_width))

        # Yan duvarların ön-üst köşesine, kulaklarla eşleşen yuvalar
        slot_top = min(wall_y + flat_W - slot_inset, wall_y + flat_W)
        slot_bottom = max(slot_top - ear_width, wall_y)
        slot_width = slot_top - slot_bottom

        if slot_width > LINE_EPSILON:
            left_slot = _polygon_rectangle(-wall_y + slot_inset, slot_bottom, ear_depth, slot_width)
            right_slot = _polygon_rectangle(flat_L + wall_y - slot_inset - ear_depth, slot_bottom, ear_depth, slot_width)
            slot_geometry = _safe_union([left_slot, right_slot])
        else:
            slot_geometry = None
    else:
        slot_geometry = None

    marks = [
        Line((flat_L * 0.25, lid_outer_y), (flat_L * 0.75, lid_outer_y), LAYER_MARK)
    ]

    return _build_flat_pattern(polygons, "0427", mark_lines=marks, difference_geometry=slot_geometry)


def generate_custom_pattern(box: BoxParams, material: Material) -> FlatPattern:
    pattern = generate_fefco_0201_pattern(box, material)
    pattern.box_type = "custom"
    return pattern


# ============================================================================
# 7. TAŞIMA DELİKLİ KOLİ (Hand-Hole Shipping Box) - 0201 varyantı
# ============================================================================
#
# Standart RSC (0201) gövdesine, iki Yan panelin orta yüksekliğine elle
# taşımayı kolaylaştıran iki dikdörtgen delik eklenir. Nakliye/taşınma
# kolilerinde dünya çapında çok yaygın bir varyanttır.
def generate_handhole_pattern(box: BoxParams, material: Material) -> FlatPattern:
    base = generate_fefco_0201_pattern(box, material)

    # Panel sırası _generate_slotted_box içinde: [glue_flap(0), Side1(1),
    # Front(2), Side2(3), Back(4), ...flap'lar]. Delikleri, panelin
    # normalize SONRASI gerçek sınırlarından (bounds) konumlandırıyoruz -
    # önceden hesaplanmış "ham" (kaydırılmamış) koordinatlar kullanmak,
    # deliği yanlışlıkla kapak/kulak bölgesine düşürebiliyordu.
    side1_body = base.polygons[1]
    side2_body = base.polygons[3]

    def _hole_for(panel_polygon):
        x0, y0, x1, y1 = panel_polygon.bounds
        panel_w, panel_h = x1 - x0, y1 - y0
        hole_w = min(panel_w * 0.5, 90.0)
        hole_h = min(panel_h * 0.15, 25.0)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        return _polygon_rectangle(cx - hole_w / 2.0, cy - hole_h / 2.0, hole_w, hole_h)

    holes = _safe_union([_hole_for(side1_body), _hole_for(side2_body)])

    return _build_flat_pattern(base.polygons, "handhole", difference_geometry=holes)


# ============================================================================
# 8. BÖLMELİ AYIRICI (Partition Divider) - Şişe/Cam Ürün Nakliyesi
# ============================================================================
#
# Kutunun iç tabanına yerleştirilen, birbirine slot-geçme ile kilitlenen
# (yapıştırıcısız) bir yatay + bir dikey şeritten oluşan "artı" bölme.
# Kutuyu 4 eşit hücreye ayırır - şişe, kavanoz, cam gibi kırılabilir
# ürünleri birbirinden ayırmak için e-ticarette çok sık kullanılır.
def generate_partition_pattern(box: BoxParams, material: Material) -> FlatPattern:
    L, W, H = float(box.length), float(box.width), float(box.height)
    t = max(float(material.thickness), 0.01)

    strip_height = _clamp(H * 0.6, 30.0, 120.0)
    slot_width = t + 0.4

    horizontal = _polygon_rectangle(0.0, 0.0, L, strip_height)

    vertical_offset_x = L + 20.0
    vertical = _polygon_rectangle(vertical_offset_x, 0.0, W, strip_height)

    # Yatay şeridin ortasında, ÜST kenardan yarı derinlik yuva
    h_slot = _polygon_rectangle(L / 2.0 - slot_width / 2.0, strip_height / 2.0, slot_width, strip_height / 2.0)
    # Dikey şeridin ortasında, ALT kenardan yarı derinlik yuva
    v_slot = _polygon_rectangle(vertical_offset_x + W / 2.0 - slot_width / 2.0, 0.0, slot_width, strip_height / 2.0)

    slots = _safe_union([h_slot, v_slot])

    return _build_flat_pattern([horizontal, vertical], "partition", difference_geometry=slots)


# ============================================================================
# 9. MENTEŞELİ KAPAKLI KENDİNDEN KİLİTLİ KUTU (Pizza/Bakery/Hediye Kutusu Tarzı)
# ============================================================================
#
# Açık tepsi (0422) gövdesine, Arka panelin üst kenarından menteşeli, tüm
# üstü kapatan tek parça bir kapak eklenir. Kapağın orta noktasından çıkan
# bir kilit dili, Ön duvarın iç yüzüne sürtünerek kapağı kapalı tutar -
# pizza kutusu, pasta kutusu ve hediye kutularında yaygın kullanılan,
# tamamen tek parça / yapıştırıcısız bir tasarım.
def generate_fefco_0421_pattern(box: BoxParams, material: Material) -> FlatPattern:
    t = max(float(material.thickness), 0.01)

    polygons, slot = _build_0422_body(box, material)

    # Panel sırası _build_0422_body içinde: [Side1(0), Front(1), Side2(2),
    # Back(3), tab(4), ...flap'lar]. Kapağı, Arka panelin (henüz normalize
    # edilmemiş, ama tutarlı) gerçek üst kenarına menteşeliyoruz.
    back_body = polygons[3]
    bx0, by0, bx1, by1 = back_body.bounds
    panel_w = bx1 - bx0

    side1_body = polygons[0]
    sx0, sy0, sx1, sy1 = side1_body.bounds
    flat_W_actual = sx1 - sx0

    lid_depth = flat_W_actual * 0.92
    lock_tab_width = min(panel_w * 0.15, 20.0)
    lock_tab_depth = max(t * 3.0, 6.0)

    polygons.append(
        _polygon_flap_with_tab(bx0, bx1, by1, +1, lid_depth, lock_tab_width, lock_tab_depth)
    )

    return _build_flat_pattern(polygons, "0421", difference_geometry=slot)


# ============================================================================
# 10. PERAKENDE TEŞHİR KUTUSU (Retail Display / POS Box)
# ============================================================================
#
# Açık tepsi (0422) gövdesine, Ön panelin büyük bölümünü kaplayan bir
# teşhir penceresi (die-cut opening) eklenir - raf üzerinde ürünün görünür
# ve kolay erişilir olmasını sağlar (Point-of-Sale / mağaza içi teşhir).
def generate_display_box_pattern(box: BoxParams, material: Material) -> FlatPattern:
    polygons, slot = _build_0422_body(box, material)

    # Panel sırası _build_0422_body içinde: [Side1(0), Front(1), Side2(2),
    # Back(3), ...]. Pencereyi Ön panelin gerçek (henüz normalize
    # edilmemiş, ama tutarlı) sınırlarından konumlandırıyoruz.
    front_body = polygons[1]
    fx0, fy0, fx1, fy1 = front_body.bounds
    panel_w, panel_h = fx1 - fx0, fy1 - fy0

    margin_x = panel_w * 0.15
    margin_top = panel_h * 0.35
    margin_bottom = panel_h * 0.1

    window = _polygon_rectangle(
        fx0 + margin_x, fy0 + margin_bottom,
        panel_w - 2 * margin_x, panel_h - margin_top - margin_bottom,
    )

    holes = _safe_union([slot, window])
    return _build_flat_pattern(polygons, "display", difference_geometry=holes)


# FABRİKA YÖNLENDİRİCİSİ
BOX_GENERATORS = {
    "0200": generate_fefco_0200_pattern,
    "0201": generate_fefco_0201_pattern,
    "0202": generate_fefco_0202_pattern,
    "0203": generate_fefco_0203_pattern,
    "0217": generate_fefco_0217_pattern,
    "0301": generate_fefco_0301_pattern,
    "0422": generate_fefco_0422_pattern,
    "0427": generate_fefco_0427_pattern,
    "0713": generate_fefco_0713_pattern,
    "handhole": generate_handhole_pattern,
    "partition": generate_partition_pattern,
    "0421": generate_fefco_0421_pattern,
    "display": generate_display_box_pattern,
    "custom": generate_custom_pattern,
}


def generate_flat_pattern(box: BoxParams, material: Material) -> FlatPattern:
    if box is None or material is None:
        raise ValueError("BoxParams veya Material boş olamaz.")

    box_type_key = box.box_type if box.box_type in BOX_GENERATORS else "0201"
    generator = BOX_GENERATORS[box_type_key]

    pattern = generator(box, material)
    pattern.lines = optimize_lines(pattern.lines)
    pattern.mark_lines = optimize_lines(pattern.mark_lines)
    pattern.update_dimensions()

    if not pattern.lines or pattern.width <= 0 or pattern.height <= 0:
        raise ValueError("Geçersiz koli açınım boyutları.")

    pattern = pattern.normalize()
    pattern.lines = optimize_lines(pattern.lines)
    pattern.mark_lines = optimize_lines(pattern.mark_lines)
    pattern.update_dimensions()
    return pattern
