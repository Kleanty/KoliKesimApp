from kolikesimapp.core.models import Sheet
from kolikesimapp.core.nesting import nest_single_pattern


def test_nest_simple_grid_no_rotation_needed():
    sheet = Sheet(width=1000, height=1000, margin=0, spacing=0)
    result = nest_single_pattern(piece_width=200, piece_height=200, sheet=sheet)
    # 1000/200 = 5 per row/col => 25 pieces
    assert result.count == 25
    assert result.piece_width == 200
    assert result.piece_height == 200


def test_nest_prefers_rotation_when_more_efficient():
    # piece 900x100 on a 1000x950 sheet: normal orientation fits only 1 row (900<=1000, but only
    # one column since piece width 900 leaves no room for a second); rotated (100x900) allows many columns
    sheet = Sheet(width=1000, height=950, margin=0, spacing=0)
    result = nest_single_pattern(piece_width=900, piece_height=100, sheet=sheet)
    # rotated: piece becomes 100 wide x 900 tall -> cols = 1000//100 = 10, rows = 950//900 = 1 => 10
    # normal: cols = 1000//900 = 1, rows = 950//100 = 9 => 9
    assert result.count == 10
    assert result.piece_width == 100
    assert result.piece_height == 900


def test_nest_with_margin_and_spacing_reduces_count():
    sheet_no_margin = Sheet(width=1000, height=1000, margin=0, spacing=0)
    sheet_with_margin = Sheet(width=1000, height=1000, margin=50, spacing=10)

    result_a = nest_single_pattern(200, 200, sheet_no_margin)
    result_b = nest_single_pattern(200, 200, sheet_with_margin)

    assert result_b.count <= result_a.count


def test_nest_placements_are_non_overlapping():
    sheet = Sheet(width=1000, height=1000, margin=5, spacing=5)
    result = nest_single_pattern(150, 100, sheet)

    pw, ph = result.piece_width, result.piece_height
    placements = result.placements
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            a, b = placements[i], placements[j]
            separated = (
                a.x + pw <= b.x or b.x + pw <= a.x or a.y + ph <= b.y or b.y + ph <= a.y
            )
            assert separated, f"Overlap detected between placement {i} and {j}"


def test_nest_zero_or_negative_piece_returns_no_placements():
    sheet = Sheet(width=1000, height=1000)
    result = nest_single_pattern(0, 100, sheet)
    assert result.count == 0
    assert result.placements == []
