import json

import pytest

from kolikesimapp.core.models import BoxParams, Material, BOX_TYPES
from kolikesimapp.core.geometry import BOX_GENERATORS, generate_flat_pattern
from kolikesimapp.core.templates import (
    ParametricTemplate,
    TemplatePoint,
    TemplateSegment,
    TEMPLATE_REGISTRY,
    register_template,
    generate_from_template,
    template_from_dict,
    template_to_dict,
    load_template_file,
    save_template_file,
    load_all_templates,
    list_template_names,
)
from kolikesimapp.core.box_factory import (
    generate_pattern,
    available_box_types,
    is_user_template,
    reload_user_templates,
    UnknownBoxTypeError,
)


# ---------------------------------------------------------------------------
# geometry.py ayrımı: FEFCO tarafı hiç etkilenmemiş olmalı
# ---------------------------------------------------------------------------

def test_geometry_py_has_no_template_leakage():
    """geometry.py, templates.py'nin hiçbir sembolünü içermemeli - tam ayrım."""
    import kolikesimapp.core.geometry as geometry_module

    assert not hasattr(geometry_module, "ParametricTemplate")
    assert not hasattr(geometry_module, "TEMPLATE_REGISTRY")
    assert not hasattr(geometry_module, "USER_TEMPLATES")


def test_all_fefco_types_still_work_after_extraction():
    """Şablon motorunu ayrı dosyaya taşımak, hiçbir FEFCO tipini bozmamalı."""
    material = Material("Karton", 3)
    for box_type in BOX_TYPES:
        box = BoxParams(box_type, length=300, width=203, height=150)
        pattern = generate_flat_pattern(box, material)
        assert len(pattern.lines) > 0
        assert pattern.width > 0 and pattern.height > 0


# ---------------------------------------------------------------------------
# ParametricTemplate motoru: temel doğruluk
# ---------------------------------------------------------------------------

def _make_rounded_template(name="test_rounded"):
    return ParametricTemplate(
        name=name,
        parameters={"radius": "20"},
        points=[
            TemplatePoint("bottom_start", "radius", "0"),
            TemplatePoint("bottom_end", "L - radius", "0"),
            TemplatePoint("right_start", "L", "radius"),
            TemplatePoint("right_end", "L", "W - radius"),
            TemplatePoint("top_start", "L - radius", "W"),
            TemplatePoint("top_end", "radius", "W"),
            TemplatePoint("left_start", "0", "W - radius"),
            TemplatePoint("left_end", "0", "radius"),
            TemplatePoint("c_br", "L - radius", "radius"),
            TemplatePoint("c_tr", "L - radius", "W - radius"),
            TemplatePoint("c_tl", "radius", "W - radius"),
            TemplatePoint("c_bl", "radius", "radius"),
        ],
        segments=[
            TemplateSegment("line", ["bottom_start", "bottom_end"]),
            TemplateSegment("arc", ["c_br"], radius_formula="radius", start_angle_deg=-90, end_angle_deg=0),
            TemplateSegment("line", ["right_start", "right_end"]),
            TemplateSegment("arc", ["c_tr"], radius_formula="radius", start_angle_deg=0, end_angle_deg=90),
            TemplateSegment("line", ["top_start", "top_end"]),
            TemplateSegment("arc", ["c_tl"], radius_formula="radius", start_angle_deg=90, end_angle_deg=180),
            TemplateSegment("line", ["left_start", "left_end"]),
            TemplateSegment("arc", ["c_bl"], radius_formula="radius", start_angle_deg=180, end_angle_deg=270),
        ],
    )


def test_template_overall_bounds_match_L_and_W():
    template = _make_rounded_template()
    material = Material("Karton", 3)
    box = BoxParams(template.name, length=300, width=200, height=100)
    register_template(template)

    pattern = template.to_flat_pattern(box, material)
    assert round(pattern.width, 1) == 300.0
    assert round(pattern.height, 1) == 200.0


def test_template_fixed_radius_does_not_scale_with_box_size():
    """KRİTİK: 'resim çerçevesi' davranışı - köşe yarıçapı sabit kalmalı,
    kutu büyüse de küçülse de (görsel ispatın otomatik testi)."""
    template = _make_rounded_template()
    material = Material("Karton", 3)

    for L, W in [(300, 200), (900, 700), (150, 150)]:
        box = BoxParams(template.name, length=L, width=W, height=100)
        pattern = template.to_flat_pattern(box, material)

        near_corner = [
            ln for ln in pattern.lines
            if ((ln.p1[0] - L) ** 2 + (ln.p1[1] - 0) ** 2) ** 0.5 < 25 and ln.length < 10
        ]
        xs = [pt for ln in near_corner for pt in (ln.p1[0], ln.p2[0])]
        ys = [pt for ln in near_corner for pt in (ln.p1[1], ln.p2[1])]

        assert round(max(xs) - min(xs), 1) == 20.0, f"L={L},W={W}: köşe yarıçapı bozuldu"
        assert round(max(ys) - min(ys), 1) == 20.0, f"L={L},W={W}: köşe yarıçapı bozuldu"


def test_formula_eval_is_restricted_no_arbitrary_code():
    """Formül motoru, izin verilenler dışında (ör. dosya okuma, import) hiçbir
    şey çalıştıramamalı - güvenlik kontrolü."""
    from kolikesimapp.core.templates import _eval_formula

    with pytest.raises(ValueError):
        _eval_formula("__import__('os').system('echo hacked')", {"L": 300, "W": 200, "H": 100, "t": 3})

    with pytest.raises(ValueError):
        _eval_formula("open('/etc/passwd')", {"L": 300, "W": 200, "H": 100, "t": 3})

    # Ama normal matematik ve izin verilen fonksiyonlar calismali
    assert _eval_formula("L / 2 + sqrt(4)", {"L": 300, "W": 200, "H": 100, "t": 3}) == 152.0


# ---------------------------------------------------------------------------
# JSON <-> Template dönüşümü (round-trip)
# ---------------------------------------------------------------------------

def test_template_json_round_trip(tmp_path):
    template = _make_rounded_template(name="roundtrip_test")
    filepath = tmp_path / "roundtrip_test.json"

    save_template_file(template, filepath)
    loaded = load_template_file(filepath)

    assert loaded.name == template.name
    assert loaded.parameters == template.parameters
    assert len(loaded.points) == len(template.points)
    assert len(loaded.segments) == len(template.segments)

    material = Material("Karton", 3)
    box = BoxParams(loaded.name, length=300, width=200, height=100)
    pattern = loaded.to_flat_pattern(box, material)
    assert pattern.width == 300.0 and pattern.height == 200.0


def test_template_from_dict_missing_field_raises_clear_error():
    with pytest.raises(ValueError):
        template_from_dict({"name": "eksik", "points": [], "segments": [{"kind": "line"}]})


def test_load_all_templates_skips_broken_json_without_crashing(tmp_path):
    good = _make_rounded_template(name="good_one")
    save_template_file(good, tmp_path / "good_one.json")

    (tmp_path / "broken.json").write_text("{ bu gecersiz json_", encoding="utf-8")

    loaded_names = load_all_templates(tmp_path)
    assert "good_one" in loaded_names
    assert "broken" not in loaded_names


# ---------------------------------------------------------------------------
# box_factory.py: birleşik giriş noktası
# ---------------------------------------------------------------------------

def test_box_factory_routes_fefco_types():
    material = Material("Karton", 3)
    box = BoxParams("0201", length=300, width=200, height=150)
    pattern = generate_pattern(box, material)
    assert pattern.width > 0 and pattern.height > 0
    assert not is_user_template("0201")


def test_box_factory_routes_user_templates():
    template = _make_rounded_template(name="factory_test_template")
    register_template(template)

    material = Material("Karton", 3)
    box = BoxParams("factory_test_template", length=300, width=200, height=100)
    pattern = generate_pattern(box, material)

    assert pattern.width == 300.0 and pattern.height == 200.0
    assert is_user_template("factory_test_template")


def test_box_factory_unknown_type_raises_instead_of_silently_substituting():
    """REGRESSION TEST - daha once bilinmeyen bir box_type sessizce FEFCO
    0201'e donusturuluyordu ("guvenli varsayilan" mantigiyla). Bu aslinda
    tehlikeliydi: kullanici farkinda olmadan TAMAMEN FARKLI bir kutu
    geometrisi hesaplanip lazere/CNC'ye gonderilebiliyordu (ornegin bozuk
    bir proje dosyasi veya yazim hatasi iceren box_type, hicbir uyari
    vermeden baska bir kutu uretiyordu). Artik bu durumda acik bir
    UnknownBoxTypeError firlatilir; GUI bunu yakalayip net bir hata mesaji
    gosterir, hicbir zaman sessizce farkli bir geometri uretmez."""
    material = Material("Karton", 3)
    box = BoxParams("hicbir_yerde_olmayan_tip", length=300, width=200, height=150)
    with pytest.raises(UnknownBoxTypeError):
        generate_pattern(box, material)


def test_available_box_types_includes_both_sources():
    template = _make_rounded_template(name="listing_test_template")
    register_template(template)

    all_types = available_box_types()
    assert "0201" in all_types          # FEFCO tarafı
    assert "listing_test_template" in all_types  # kullanıcı şablonu tarafı


def test_boxparams_validate_accepts_registered_user_template():
    template = _make_rounded_template(name="validate_test_template")
    register_template(template)

    box = BoxParams("validate_test_template", length=300, width=200, height=100)
    assert box.validate() is True


def test_boxparams_validate_rejects_truly_unknown_type():
    box = BoxParams("kesinlikle_boyle_bir_tip_yok", length=300, width=200, height=100)
    assert box.validate() is False


# --- Güvenlik / sağlamlık regresyon testleri (kod incelemesi) -------------

import pytest as _pytest
from kolikesimapp.core.templates import _eval_formula, validate_template_name, template_from_dict


@_pytest.mark.parametrize("evil", [
    "().__class__.__base__.__subclasses__()",
    "__import__('os').system('echo pwned')",
    "[c for c in ().__class__.__base__.__subclasses__()]",
    "L.__class__",
    "open('/etc/passwd')",
    "9**9**9",
    "lambda: 1",
])
def test_formula_rejects_code_execution(evil):
    with _pytest.raises(ValueError):
        _eval_formula(evil, {"L": 100.0})


def test_formula_allows_math():
    assert _eval_formula("max(L/2, 10) - sqrt(16) + 2**3", {"L": 100.0}) == 54.0
    assert _eval_formula(5, {}) == 5.0


@_pytest.mark.parametrize("name", ["../evil", "a/b", "", "0201", "x" * 80, None])
def test_template_name_rejected(name):
    with _pytest.raises(ValueError):
        validate_template_name(name)


def test_template_undefined_point_rejected():
    data = {"name": "t", "points": [{"name": "a", "x": "0", "y": "0"}],
            "segments": [{"kind": "line", "points": ["a", "zzz"]}]}
    with _pytest.raises(ValueError):
        template_from_dict(data)
