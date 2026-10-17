from kolikesimapp.core.models import Product, Layout, Tolerance, BoxParams, Material, BOX_TYPES
from kolikesimapp.core.geometry import (
    compute_internal_box_dimensions,
    compute_product_positions,
    generate_flat_pattern,
    generate_fefco_0201_pattern,
    _rsc_flap_depths,
    _flat_dimension,
    LAYER_CUT,
    LAYER_FOLD,
)


def test_compute_internal_box_dimensions_simple():
    product = Product(width=100, depth=100, height=100)
    layout = Layout(x_count=2, y_count=2, z_count=2)
    tolerance = Tolerance(gap_x=0, gap_y=0, gap_z=0, wall_x=0, wall_y=0, wall_z=0)

    length, width, height = compute_internal_box_dimensions(product, layout, tolerance)

    assert length == 200
    assert width == 200
    assert height == 200
    assert layout.total == 8


def test_compute_internal_box_dimensions_with_tolerance():
    product = Product(width=100, depth=150, height=50)
    layout = Layout(x_count=4, y_count=3, z_count=2)
    tolerance = Tolerance(gap_x=2, gap_y=2, gap_z=3, wall_x=3, wall_y=3, wall_z=4)

    length, width, height = compute_internal_box_dimensions(product, layout, tolerance)

    assert length == 412   # 4*100 + 3*2 + 2*3
    assert width == 460    # 3*150 + 2*2 + 2*3
    assert height == 111   # 2*50 + 1*3 + 2*4


def test_compute_product_positions_count_matches_layout_total():
    product = Product(width=10, depth=10, height=10)
    layout = Layout(x_count=2, y_count=2, z_count=2)
    tolerance = Tolerance()

    positions = compute_product_positions(product, layout, tolerance)
    assert len(positions) == layout.total == 8
    assert len(set(positions)) == 8


# ---------------------------------------------------------------------------
# Kritik regresyon testi 1: major/minor kapak derinliği doğru eksene bağlı olmalı
# ---------------------------------------------------------------------------

def test_side_flap_depth_scales_with_length_not_width():
    """Yan panel kapaklarının derinliği kutunun UZUNLUĞUNA (L) bağlı olmalı,
    genişliğine (W) değil - aksi halde uzun/dar kutularda ortada kapanmayan
    bir boşluk oluşur."""
    material = Material("Karton", 3)

    box_a = BoxParams("0201", length=300, width=200, height=150, minor_flap_clearance=5)
    box_b = BoxParams("0201", length=600, width=200, height=150, minor_flap_clearance=5)

    pattern_a = generate_flat_pattern(box_a, material)
    pattern_b = generate_flat_pattern(box_b, material)

    assert pattern_b.height - pattern_a.height > 250


def test_rsc_major_flap_closes_the_box_top():
    """Ön/Arka (major) kapaklar W'nin neredeyse tamamını kapatmalı."""
    t = 3.0
    flat_W = _flat_dimension(200.0, t)
    flat_L = _flat_dimension(300.0, t)
    major_depth, _ = _rsc_flap_depths(flat_L, flat_W, t, clearance=5.0)

    gap_at_center = flat_W - 2 * major_depth
    assert 0 <= gap_at_center <= 2 * t


def test_0203_full_overlap_deeper_than_0201():
    t = 3.0
    flat_L = _flat_dimension(300.0, t)
    flat_W = _flat_dimension(200.0, t)

    major_0201, _ = _rsc_flap_depths(flat_L, flat_W, t, clearance=5.0)
    major_0203, _ = _rsc_flap_depths(flat_L, flat_W, t, clearance=5.0, full_overlap=True)

    assert major_0203 > major_0201 * 1.5


# ---------------------------------------------------------------------------
# Kritik regresyon testi 2: bitişik kapaklar arasında gerçek KESİM olmalı
# ---------------------------------------------------------------------------

def test_adjacent_flaps_are_cut_apart_not_fused_by_fold():
    """KRİTİK: Bitişik iki kapak, farklı yönlere katlandığı için aralarında
    MUTLAKA gerçek bir KESİM (CUT) olmalı - asla bir FOLD ile birbirine
    bağlı kalmamalılar. Aksi halde lazer o köşeyi kesmez, kapaklar
    birbirine yapışık kalır ve kutu monte edilemez."""
    material = Material("Karton", 3)
    flat_H = _flat_dimension(150.0, 3.0)

    known_hinge_exceptions = {
        "0422": 1, "display": 1,   # tab -> duvar menteşesi
        "0421": 1,                  # tab -> duvar menteşesi (kapağın kendi menteşesi flat_H'ye eşit, ayrıca sayılmaz)
        "0427": 4,                  # taban<->yan duvar (x2) + kulak<->kapak (x2)
    }

    for box_type in ("0200", "0201", "0202", "0203", "0217", "0301", "0713", "custom"):
        box = BoxParams(box_type, length=300, width=203, height=150, minor_flap_clearance=5)
        pattern = generate_flat_pattern(box, material)

        bad_folds = [
            ln for ln in pattern.lines
            if ln.layer == LAYER_FOLD and ln.p1[0] == ln.p2[0]
            and abs(abs(ln.p1[1] - ln.p2[1]) - flat_H) > 0.5
        ]
        assert not bad_folds, f"{box_type}: bitişik kapaklar arasında hatalı FOLD bulundu: {bad_folds}"

    for box_type, expected_count in known_hinge_exceptions.items():
        box = BoxParams(box_type, length=300, width=203, height=150, minor_flap_clearance=5)
        pattern = generate_flat_pattern(box, material)
        suspicious = [
            ln for ln in pattern.lines
            if ln.layer == LAYER_FOLD and ln.p1[0] == ln.p2[0]
            and abs(abs(ln.p1[1] - ln.p2[1]) - flat_H) > 0.5
        ]
        assert len(suspicious) == expected_count, (
            f"{box_type}: beklenen {expected_count} meşru menteşe, bulunan {len(suspicious)}: {suspicious}"
        )


# ---------------------------------------------------------------------------
# Genel yapı ve dispatch testleri
# ---------------------------------------------------------------------------

def test_fefco_0201_flat_pattern_structure():
    box = BoxParams(box_type="0201", length=300, width=200, height=150, minor_flap_clearance=5)
    material = Material("Karton", 3)

    pattern = generate_fefco_0201_pattern(box, material)

    counts = pattern.line_count_by_layer()
    assert counts[LAYER_CUT] > 0
    assert counts[LAYER_FOLD] > 0

    min_x, min_y, max_x, max_y = pattern.bounds()
    assert min_x >= 0 and min_y >= 0
    assert round(max_x - min_x, 2) == round(pattern.width, 2)
    assert round(max_y - min_y, 2) == round(pattern.height, 2)


def test_generate_flat_pattern_dispatch():
    box = BoxParams(box_type="0201")
    material = Material()
    pattern = generate_flat_pattern(box, material)
    assert pattern.box_type == "0201"
    assert len(pattern.lines) > 0


def test_generate_flat_pattern_unknown_type_falls_back_to_0201():
    """Bilinmeyen bir box_type verilirse, motor güvenli varsayılan olan
    0201'e (RSC) düşmelidir (çökmemelidir)."""
    box = BoxParams(box_type="nonexistent_box_type")
    material = Material()
    pattern = generate_flat_pattern(box, material)
    assert pattern.box_type == "0201"


def test_all_box_types_generate_valid_patterns():
    """models.BOX_TYPES içindeki tüm tipler geçerli, sıfır olmayan bir açınım üretmeli."""
    material = Material("Karton", 3)
    for box_type in BOX_TYPES:
        box = BoxParams(box_type=box_type, length=300, width=200, height=150)
        pattern = generate_flat_pattern(box, material)

        assert len(pattern.lines) > 0
        assert pattern.width > 0
        assert pattern.height > 0

        for line in pattern.lines:
            assert line.p1 != line.p2, f"{box_type}: zero-length line found"


def test_0200_has_no_flap_lines_beyond_body():
    material = Material("Karton", 3)
    p_0200 = generate_flat_pattern(BoxParams("0200", length=300, width=200, height=150), material)
    p_0201 = generate_flat_pattern(BoxParams("0201", length=300, width=200, height=150), material)
    assert p_0200.height < p_0201.height


def test_0422_has_no_glue_flap_and_uses_tab_lock():
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(BoxParams("0422", length=300, width=200, height=150), material)

    flat_L = _flat_dimension(300.0, 3.0)
    flat_W = _flat_dimension(200.0, 3.0)
    expected_min_width = 2 * flat_L + 2 * flat_W - 20
    assert pattern.width >= expected_min_width


def test_0427_has_ear_lock_geometry():
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(BoxParams("0427", length=300, width=200, height=150), material)
    assert pattern.line_count_by_layer()[LAYER_CUT] >= 20


def test_0301_lid_bigger_than_base_for_telescoping_fit():
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(BoxParams("0301", length=300, width=200, height=150), material)
    base_only = generate_flat_pattern(BoxParams("0201", length=300, width=200, height=150), material)
    assert pattern.width > base_only.width


def test_0217_lid_deeper_than_0301():
    material = Material("Karton", 3)
    p_0301 = generate_flat_pattern(BoxParams("0301", length=300, width=200, height=150), material)
    p_0217 = generate_flat_pattern(BoxParams("0217", length=300, width=200, height=150), material)
    assert p_0217.width > p_0301.width


def test_0713_has_tongue_and_slot_lock_geometry():
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(BoxParams("0713", length=300, width=200, height=150), material)
    assert pattern.line_count_by_layer()[LAYER_CUT] >= 20


def test_handhole_has_two_cutout_holes():
    material = Material("Karton", 3)
    base = generate_flat_pattern(BoxParams("0201", length=300, width=200, height=150), material)
    handhole = generate_flat_pattern(BoxParams("handhole", length=300, width=200, height=150), material)
    assert handhole.line_count_by_layer()[LAYER_CUT] > base.line_count_by_layer()[LAYER_CUT]


def test_partition_slots_are_half_strip_height_and_material_width():
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(BoxParams("partition", length=300, width=200, height=150), material)
    short_segments = [ln.length for ln in pattern.lines if ln.layer == "CUT" and ln.length < 10]
    assert short_segments, "Yuva kenarı bulunamadı"
    assert all(2.5 <= s <= 5.0 for s in short_segments)


def test_0421_covers_most_of_the_width():
    material = Material("Karton", 3)
    base = generate_flat_pattern(BoxParams("0422", length=300, width=200, height=150), material)
    pattern = generate_flat_pattern(BoxParams("0421", length=300, width=200, height=150), material)
    assert pattern.height > base.height


def test_display_box_has_front_window_cutout():
    material = Material("Karton", 3)
    base = generate_flat_pattern(BoxParams("0422", length=300, width=200, height=150), material)
    display = generate_flat_pattern(BoxParams("display", length=300, width=200, height=150), material)
    assert display.line_count_by_layer()[LAYER_CUT] > base.line_count_by_layer()[LAYER_CUT]


def test_custom_is_labeled_correctly_not_inherited_type():
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(BoxParams("custom", length=300, width=200, height=150), material)
    assert pattern.box_type == "custom"


def test_all_box_types_have_expected_count():
    assert len(BOX_TYPES) == 14
    assert set(BOX_TYPES) == {
        "0200", "0201", "0202", "0203", "0217", "0301", "0422", "0427", "0713",
        "handhole", "partition", "0421", "display", "custom",
    }
