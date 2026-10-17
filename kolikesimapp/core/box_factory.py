"""
KoliKesimApp - Birleşik Kutu Üretim Noktası (box_factory.py)

Bu dosya, geometry.py (FEFCO formülleri) ve templates.py (kullanıcı
şablonları) sistemlerini birleştiren TEK giriş noktasıdır. GUI (veya başka
herhangi bir çağıran kod), koli tipi FEFCO mu yoksa kullanıcı şablonu mu
diye kendi kontrol etmek zorunda kalmadan, sadece `generate_pattern(box,
material)` çağırır.

Neden ayrı bir dosya (geometry.py'ye eklemek yerine)?
- geometry.py, yalnızca FEFCO formüllerini bilir; templates.py'den haberi
  YOKTUR (tek yönlü bağımlılık: box_factory -> geometry + templates).
  Bu sayede geometry.py hiçbir zaman kullanıcı şablonlarından etkilenmez.
- templates.py da geometry.py'nin FEFCO fonksiyonlarından haberi yoktur -
  yalnızca genel amaçlı (FlatPattern, Line, vb.) yapı taşlarını kullanır.

Kullanım:
    from .box_factory import generate_pattern, available_box_types

    pattern = generate_pattern(box, material)   # FEFCO veya kullanıcı şablonu, farketmez
"""

from __future__ import annotations

from typing import List

from .geometry import BOX_GENERATORS, FlatPattern, generate_flat_pattern
from .models import BoxParams, Material
from .templates import (
    TEMPLATE_REGISTRY,
    generate_from_template,
    load_all_templates,
)

# Uygulama açılışında kullanıcı şablonlarını (user_templates/*.json) bir kez
# yükle. Bozuk bir dosya varsa yalnızca o atlanır (bkz. templates.py).
load_all_templates()


def available_box_types() -> List[str]:
    """FEFCO kodları + kayıtlı kullanıcı şablonlarının tam listesini döndürür."""
    return list(BOX_GENERATORS.keys()) + list(TEMPLATE_REGISTRY.keys())


def is_user_template(box_type: str) -> bool:
    return box_type in TEMPLATE_REGISTRY


def get_display_name(box_type: str) -> str:
    """Bir koli tipi için kullanıcıya gösterilecek insan-okur ismi döndürür.

    FEFCO kodları için "FEFCO 0201" gibi, kullanıcı şablonları için
    şablonun kendi `display_name` alanı (varsa) kullanılır - GUI'nin her
    ikisini de aynı mantıkla, doğru etiketle listeleyebilmesi içindir.
    """
    if box_type in TEMPLATE_REGISTRY:
        return TEMPLATE_REGISTRY[box_type].display_name or box_type
    if box_type.isdigit():
        return f"FEFCO {box_type.upper()}"
    return box_type.capitalize()


class UnknownBoxTypeError(ValueError):
    """box_type ne FEFCO kataloğunda ne de kayıtlı kullanıcı şablonlarında
    bulunamadığında fırlatılır.

    ÖNEMLİ (güvenlik kararı): Daha önce bu durumda sessizce FEFCO 0201'e
    "güvenli varsayılan" olarak dönülüyordu. Bu YANLIŞ bir güvenlik
    tercihiydi - kullanıcı farkında olmadan tamamen FARKLI bir kutu
    geometrisi CNC/lazere gönderilebiliyordu (ör. bozuk bir proje dosyası
    veya yazım hatası içeren box_type, sessizce 0201 koli üretip hiçbir
    uyarı vermiyordu). Üretim güvenliği açısından "sessizce yanlış sonuç"
    "açıkça durmak"tan daha tehlikelidir, bu yüzden artık burada hata
    fırlatılır; GUI bunu yakalayıp kullanıcıya net bir mesaj gösterir."""


def generate_pattern(box: BoxParams, material: Material) -> FlatPattern:
    """Koli tipine göre FEFCO formülü veya kullanıcı şablonundan açınım üretir.

    Önce FEFCO kataloğuna (geometry.BOX_GENERATORS) bakar; orada yoksa
    kullanıcı şablonlarına (templates.TEMPLATE_REGISTRY) bakar; o da yoksa
    UnknownBoxTypeError fırlatır (artık sessizce başka bir kutuya DÖNMEZ -
    bkz. UnknownBoxTypeError docstring'i).
    """
    if box is None or material is None:
        raise ValueError("BoxParams veya Material boş olamaz.")

    if box.box_type in BOX_GENERATORS:
        return generate_flat_pattern(box, material)

    if box.box_type in TEMPLATE_REGISTRY:
        return generate_from_template(box, material)

    known = available_box_types()
    raise UnknownBoxTypeError(
        f"Bilinmeyen koli tipi: '{box.box_type}'. "
        f"Bu bir FEFCO kodu değil ve kayıtlı bir kullanıcı şablonu da değil. "
        f"Bilinen tipler: {', '.join(known)}. "
        f"(Not: güvenlik nedeniyle başka bir koli tipine otomatik geçiş yapılmaz; "
        f"yanlış geometri üretilip lazere gönderilmesindense işlem durdurulur.)"
    )


def reload_user_templates() -> List[str]:
    """user_templates/ klasörünü yeniden tarar (ör. uygulama açıkken yeni
    bir .json dosyası eklendiğinde, yeniden başlatmadan görünmesi için)."""
    TEMPLATE_REGISTRY.clear()
    return load_all_templates()
