import datetime

from kolikesimapp.core.project import make_output_folder_name, ensure_unique_folder


def test_output_folder_name_has_second_precision():
    """Dakika hassasiyeti, ayni dakika icinde iki export'u ayirt edemiyordu.
    Artik saniye de isimde yer aliyor (bkz. ensure_unique_folder testi icin
    asil cakisma korumasi orada)."""
    ts = datetime.datetime(2026, 8, 21, 21, 38, 5)
    name = make_output_folder_name(300, 200, 150, ts)
    assert name == "Koli_300x200x150_2026-08-21_21-38-05"


def test_ensure_unique_folder_returns_as_is_when_free(tmp_path):
    result = ensure_unique_folder(tmp_path, "Koli_300x200x150_2026-08-21_21-38-05")
    assert result == tmp_path / "Koli_300x200x150_2026-08-21_21-38-05"
    assert not result.exists()


def test_ensure_unique_folder_never_collides_with_existing_output():
    """REGRESSION TEST - daha once ayni dakikada iki export yapilirsa, ayni
    klasor adi uretilip bir onceki ciktinin uzerine sessizce yazilabiliyordu.
    Artik var olan bir klasorle karsilasinca _2, _3, ... eklenerek asla
    mevcut bir ciktinin uzerine yazilmiyor."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp)
        base_name = "Koli_300x200x150_2026-08-21_21-38-05"
        (parent / base_name).mkdir()

        second = ensure_unique_folder(parent, base_name)
        assert second.name == f"{base_name}_2"
        second.mkdir()

        third = ensure_unique_folder(parent, base_name)
        assert third.name == f"{base_name}_3"


def test_from_dict_ignores_unknown_keys_and_roundtrips_schema():
    from kolikesimapp.core.models import Project
    d = Project().to_dict()
    assert d["schema_version"] == 1
    d["box"]["future_field"] = 1
    assert Project.from_dict(d).box.length == 300.0


def test_from_dict_rejects_newer_schema_and_garbage():
    import pytest
    from kolikesimapp.core.models import Project
    with pytest.raises(ValueError):
        Project.from_dict({"schema_version": 99})
    with pytest.raises(ValueError):
        Project.from_dict({"box": "x"})
