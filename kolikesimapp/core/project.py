"""
Proje kaydetme/açma / Project save & load

Proje verisi düz JSON olarak saklanır. AI/servis bağımlılığı yoktur.
"""

import json
from pathlib import Path

from .models import Project


def save_project(project: Project, filepath: str) -> str:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
    return str(path)


def load_project(filepath: str) -> Project:
    path = Path(filepath)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Project.from_dict(data)


def make_output_folder_name(box_length: float, box_width: float, box_height: float, timestamp) -> str:
    """'Koli_300x200x150_2026-08-21_21-38-05' formatında klasör adı üretir.

    Not: Saniye hassasiyeti bile aynı anda tetiklenen iki export'u (ör. çift
    tıklama, veya otomasyon/script ile art arda çağrı) ayırt etmeye yetmez.
    Gerçek çakışma koruması `ensure_unique_folder()` ile sağlanır - bu
    fonksiyon yalnızca OKUNABİLİR bir isim üretir.
    """
    ts = timestamp.strftime("%Y-%m-%d_%H-%M-%S")

    def fmt(v: float) -> str:
        return str(int(v)) if float(v).is_integer() else str(v)

    return f"Koli_{fmt(box_length)}x{fmt(box_width)}x{fmt(box_height)}_{ts}"


def ensure_unique_folder(parent: Path, folder_name: str) -> Path:
    """`parent / folder_name` zaten varsa, `_2`, `_3`, ... ekleyerek var
    olmayan bir klasör yolu döndürür (hiçbir zaman mevcut bir çıktıyı
    sessizce üzerine yazmaz / karıştırmaz)."""
    parent = Path(parent)
    candidate = parent / folder_name
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = parent / f"{folder_name}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1
