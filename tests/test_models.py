from kolikesimapp.core.models import (
    Product, Layout, Tolerance, BoxParams, Material, Sheet, Laser, Project,
)


def test_layout_total():
    layout = Layout(x_count=4, y_count=3, z_count=2)
    assert layout.total == 24


def test_product_validate():
    assert Product(100, 150, 50).validate() is True
    assert Product(0, 150, 50).validate() is False
    assert Product(100, 150, 50, rotation=45).validate() is False


def test_tolerance_auto():
    tol = Tolerance()
    tol.apply_auto(Product(100, 150, 50))
    assert tol.gap_x == max(1.0, round(100 * 0.02, 1))
    assert tol.validate() is True


def test_project_roundtrip_dict():
    proj = Project(project_name="Test_01")
    proj.product = Product(120, 80, 40)
    proj.layout = Layout(2, 2, 2)

    data = proj.to_dict()
    restored = Project.from_dict(data)

    assert restored.project_name == "Test_01"
    assert restored.product.width == 120
    assert restored.layout.total == 8


def test_box_validate_type():
    assert BoxParams(box_type="0201", length=300, width=200, height=150).validate() is True
    assert BoxParams(box_type="unknown_type").validate() is False


def test_material_and_sheet_and_laser_validate():
    assert Material("Karton", 3.0).validate() is True
    assert Material("Karton", 0).validate() is False
    assert Sheet(1000, 2000).validate() is True
    assert Sheet(0, 2000).validate() is False
    assert Laser("CO2", 40).validate() is True
    assert Laser("Lazer-X", 40).validate() is False
