"""
KoliKesimApp - Data Models Module
Professional packaging parameters, materials, and project state representation.
"""

from dataclasses import dataclass, field, asdict, fields
from typing import Any, Dict


@dataclass
class Product:
    """Single packed item dimensions (mm) and rotation."""
    width: float = 100.0
    depth: float = 150.0
    height: float = 50.0
    rotation: float = 0.0

    def validate(self) -> bool:
        return self.width > 0 and self.depth > 0 and self.height > 0 \
            and self.rotation in (0, 90, 180, 270)


@dataclass
class Layout:
    """3D product array / layout configuration."""
    x_count: int = 1
    y_count: int = 1
    z_count: int = 1

    @property
    def total(self) -> int:
        return max(0, self.x_count) * max(0, self.y_count) * max(0, self.z_count)

    def validate(self) -> bool:
        return self.x_count >= 1 and self.y_count >= 1 and self.z_count >= 1


@dataclass
class Tolerance:
    """Clearances and wall offsets (mm)."""
    gap_x: float = 2.0
    gap_y: float = 2.0
    gap_z: float = 3.0
    wall_x: float = 3.0
    wall_y: float = 3.0
    wall_z: float = 4.0
    auto: bool = False

    def apply_auto(self, product: "Product") -> None:
        self.gap_x = max(1.0, round(product.width * 0.02, 1))
        self.gap_y = max(1.0, round(product.depth * 0.02, 1))
        self.gap_z = max(1.0, round(product.height * 0.03, 1))
        self.wall_x = max(2.0, round(product.width * 0.03, 1))
        self.wall_y = max(2.0, round(product.depth * 0.03, 1))
        self.wall_z = max(3.0, round(product.height * 0.04, 1))

    def validate(self) -> bool:
        values = [self.gap_x, self.gap_y, self.gap_z, self.wall_x, self.wall_y, self.wall_z]
        return all(v >= 0 for v in values)


# Endüstriyel FEFCO sınıflandırma kodları / Industrial FEFCO classification codes
#
# Not: "Tam bindirme" (full overlap) kolinin doğru FEFCO kodu 0203'tür
# (0210 değil - bu yaygın bir karışıklıktır; kaynak: FEFCO kod kılavuzları,
# Box Factory, Dairi-Pak, TPC Packaging referansları).
BOX_TYPES = (
    "0200",         # FEFCO 0200: Kapaksız Basit Gövde (Ekonomik, üst/alt kapak yok)
    "0201",         # FEFCO 0201: Standart RSC Koli (Kapaklar ortada birleşir) - dünyada en çok kullanılan
    "0202",         # FEFCO 0202: Kısmi Bindirmeli Koli (Kapaklar biraz daha derin biner)
    "0203",         # FEFCO 0203: Tam Bindirmeli Koli (Kapaklar neredeyse tamamen üst üste biner)
    "0217",         # FEFCO 0217: Derin Kapaklı Teleskopik Kutu (Arşiv/Depolama)
    "0301",         # FEFCO 0301: Sığ Kapaklı Teleskopik Kutu (Ayrı Taban + Kapak)
    "0422",         # FEFCO 0422: Kendinden Kilitli Tepsi (Dilli/Yuvalı, yapıştırıcısız)
    "0427",         # FEFCO 0427: Kendinden Kilitli Kargo Kutusu (Kilit Kulaklı / Ear-Lock) - e-ticaret favorisi
    "0713",         # FEFCO 0713: Crash-Lock Otomatik Taban + Kilit Dilli Üst Kapak - fulfillment favorisi
    "handhole",     # Taşıma Delikli Koli (0201 varyantı) - nakliye/taşınma kolisi
    "partition",    # Bölmeli Ayırıcı (şişe/cam ürün nakliyesi)
    "0421",         # FEFCO 0421: Kapaklı Kendinden Kilitli Kutu (pizza/hediye kutusu tarzı)
    "display",      # Perakende Teşhir Kutusu (POS / raf kutusu)
    "custom",       # Özel Parametrik Koli (0201 tabanlı, genişletilebilir)
)


@dataclass
class BoxParams:
    """Internal box sizing parameters (mm)."""
    box_type: str = "0201"
    length: float = 300.0
    width: float = 200.0
    height: float = 150.0
    minor_flap_clearance: float = 5.0
    auto_clearance: bool = True

    def apply_auto_clearance(self, material: "Material") -> None:
        if self.auto_clearance:
            self.minor_flap_clearance = max(2.0, round(material.thickness * 1.5, 1))

    def validate(self) -> bool:
        basic_checks = (
            self.length > 0 and self.width > 0 and self.height > 0
            and self.minor_flap_clearance >= 0
        )
        if not basic_checks:
            return False

        if self.box_type in BOX_TYPES:
            return True

        # BOX_TYPES'ta yoksa, kayıtlı bir kullanıcı şablonu (user_templates/
        # altındaki bir .json dosyası) olabilir. Döngüsel import'tan
        # kaçınmak için bu kontrol yalnızca gerektiğinde (lazy) yapılır -
        # models.py, box_factory.py'yi modül yüklenirken DEĞİL, yalnızca
        # bu satır çalıştığında içeri aktarır.
        try:
            from .box_factory import available_box_types
            return self.box_type in available_box_types()
        except ImportError:
            return False


@dataclass
class Material:
    """Sheet material properties."""
    name: str = "Karton"
    thickness: float = 3.0

    def validate(self) -> bool:
        return bool(self.name) and self.thickness > 0


@dataclass
class Sheet:
    """Raw sheet dimensions and margins."""
    width: float = 1000.0
    height: float = 2000.0
    margin: float = 5.0
    spacing: float = 5.0

    def validate(self) -> bool:
        return self.width > 0 and self.height > 0 and self.margin >= 0 and self.spacing >= 0


@dataclass
class Laser:
    """Laser cutting specifications."""
    laser_type: str = "CO2"
    power_watt: float = 40.0

    def validate(self) -> bool:
        return self.laser_type in ("CO2", "Diyot") and self.power_watt > 0


PROJECT_SCHEMA_VERSION = 1


def _build(cls, data):
    """Sözlükten dataclass üretir; bilinmeyen anahtarları yok sayar (ileri/geri
    uyumluluk) ve sözlük olmayan girdiyi net bir hatayla reddeder."""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError(f"'{cls.__name__}' için nesne bekleniyordu, alınan: {type(data).__name__}")
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Project:
    """Root application project container."""
    project_name: str = "Koli_01"
    design_mode: str = "product_to_box"
    product: Product = field(default_factory=Product)
    layout: Layout = field(default_factory=Layout)
    tolerance: Tolerance = field(default_factory=Tolerance)
    box: BoxParams = field(default_factory=BoxParams)
    material: Material = field(default_factory=Material)
    sheet: Sheet = field(default_factory=Sheet)
    laser: Laser = field(default_factory=Laser)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = PROJECT_SCHEMA_VERSION
        return data

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Project":
        if not isinstance(data, dict):
            raise ValueError("Proje dosyası geçerli bir JSON nesnesi değil.")
        version = data.get("schema_version", 1)
        if not isinstance(version, int) or version > PROJECT_SCHEMA_VERSION:
            raise ValueError(
                f"Bu proje dosyası daha yeni bir sürümle oluşturulmuş (schema_version={version}). "
                f"Uygulamayı güncelleyin."
            )
        proj = Project()
        proj.project_name = data.get("project_name", proj.project_name)
        proj.design_mode = data.get("design_mode", proj.design_mode)
        proj.product = _build(Product, data.get("product"))
        proj.layout = _build(Layout, data.get("layout"))
        proj.tolerance = _build(Tolerance, data.get("tolerance"))
        proj.box = _build(BoxParams, data.get("box"))
        proj.material = _build(Material, data.get("material"))
        proj.sheet = _build(Sheet, data.get("sheet"))
        proj.laser = _build(Laser, data.get("laser"))
        return proj
