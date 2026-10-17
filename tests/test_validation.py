from kolikesimapp.core.models import (
    Project, Product, Layout, Tolerance, BoxParams, Material, Sheet, Laser,
)
from kolikesimapp.core.geometry import generate_flat_pattern
from kolikesimapp.core.nesting import nest_single_pattern
from kolikesimapp.core.validation import (
    validate_project,
    validate_flat_pattern_fits_sheet,
    check_zero_length_and_duplicate_lines,
    check_overlaps,
    check_sheet_bounds,
    has_errors,
    LEVEL_ERROR,
)


def _valid_project():
    proj = Project()
    proj.product = Product(100, 150, 50)
    proj.layout = Layout(4, 3, 2)
    proj.tolerance = Tolerance(2, 2, 3, 3, 3, 4)
    proj.box = BoxParams("0201", 412, 460, 111)
    proj.material = Material("Karton", 3)
    proj.sheet = Sheet(2000, 3000)
    proj.laser = Laser("CO2", 40)
    return proj


def test_validate_project_all_ok():
    proj = _valid_project()
    results = validate_project(proj)
    assert not has_errors(results)


def test_validate_project_catches_invalid_box():
    proj = _valid_project()
    proj.box.length = -10
    results = validate_project(proj)
    assert has_errors(results)


def test_validate_flat_pattern_fits_sheet_ok():
    box = BoxParams("0201", 300, 200, 150)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    results = validate_flat_pattern_fits_sheet(pattern, sheet_width=2000, sheet_height=1000, margin=5)
    assert not has_errors(results)


def test_validate_flat_pattern_too_big_for_sheet():
    box = BoxParams("0201", 900, 900, 900)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    results = validate_flat_pattern_fits_sheet(pattern, sheet_width=500, sheet_height=500, margin=5)
    assert has_errors(results)


def test_check_zero_length_and_duplicates_clean_pattern():
    box = BoxParams("0201", 300, 200, 150)
    material = Material("Karton", 3)
    pattern = generate_flat_pattern(box, material)

    results = check_zero_length_and_duplicate_lines(pattern)
    assert not has_errors(results)


def test_check_overlaps_and_bounds_for_valid_nesting():
    sheet = Sheet(1000, 1000, margin=5, spacing=5)
    result = nest_single_pattern(150, 100, sheet)

    overlap_results = check_overlaps(result)
    bounds_results = check_sheet_bounds(result, sheet.width, sheet.height, sheet.margin)

    assert not has_errors(overlap_results)
    assert not has_errors(bounds_results)
