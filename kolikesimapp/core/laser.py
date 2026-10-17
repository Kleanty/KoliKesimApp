"""
KoliKesimApp - Laser Cutting & Engraving Parameter Engine
Professional database for CO2 and Diode lasers across Cardboard, Corrugated, MDF, and Acrylic.
"""

from dataclasses import dataclass
from typing import List, Optional
from .models import Laser, Material


@dataclass
class LaserRecommendation:
    speed_mm_min: float
    power_percent: float
    passes: int
    air_assist: str = "Orta/Yüksek"
    notes: str = ""


def recommend_parameters(laser: Laser, material: Material) -> Optional[LaserRecommendation]:
    """
    Lazer tipi, gücü, malzeme cinsi ve kalınlığına göre endüstriyel standartlarda
    kesim ve kazıma parametreleri önerir.
    """
    mat_name = material.name.lower()
    t = material.thickness
    l_type = laser.laser_type.upper()
    power = laser.power_watt

    # 1. KARTON / MUKAVVA / OLUKLU KARTON
    if "karton" in mat_name or "mukavva" in mat_name or "flute" in mat_name:
        if l_type == "CO2":
            if power <= 40:
                return LaserRecommendation(speed_mm_min=3000.0, power_percent=35.0, passes=1, air_assist="Düşük", notes="Temiz kesim, yanma riski çok düşük.")
            elif power <= 80:
                return LaserRecommendation(speed_mm_min=5000.0, power_percent=30.0, passes=1, air_assist="Düşük", notes="Yüksek hızda kusursuz sonuç.")
            else:
                return LaserRecommendation(speed_mm_min=7500.0, power_percent=25.0, passes=1, air_assist="Düşük", notes="Endüstriyel yüksek hız.")
        else: # Diyot (Diode - 450nm)
            if power <= 10:
                return LaserRecommendation(speed_mm_min=1200.0, power_percent=60.0, passes=1, air_assist="Orta", notes="Diyot lazer ile dikkatli olun, kolay tutuşur.")
            else:
                return LaserRecommendation(speed_mm_min=2000.0, power_percent=50.0, passes=1, air_assist="Orta", notes="Güçlü diyot ile hızlı kesim.")

    # 2. MDF (Medium-Density Fiberboard)
    elif "mdf" in mat_name or "ahşap" in mat_name:
        if l_type == "CO2":
            if t <= 3.0:
                if power <= 40:
                    return LaserRecommendation(speed_mm_min=400.0, power_percent=85.0, passes=1, air_assist="Yüksek", notes="3mm MDF için 40W sınırda, temiz hava desteği şarttır.")
                elif power <= 80:
                    return LaserRecommendation(speed_mm_min=1200.0, power_percent=80.0, passes=1, air_assist="Yüksek", notes="İdeal endüstriyel kesim hızı.")
                else:
                    return LaserRecommendation(speed_mm_min=2000.0, power_percent=75.0, passes=1, air_assist="Yüksek", notes="Yüksek güçlü CO2 ile seri kesim.")
            elif t <= 6.0:
                if power <= 50:
                    return LaserRecommendation(speed_mm_min=200.0, power_percent=90.0, passes=2, air_assist="Yüksek", notes="Kalın MDF, düşük hız ve 2 pas önerilir.")
                else:
                    return LaserRecommendation(speed_mm_min=600.0, power_percent=85.0, passes=1, air_assist="Yüksek", notes="Güçlü CO2 ile tek pas kalın MDF kesimi.")
            else:
                return LaserRecommendation(speed_mm_min=300.0, power_percent=95.0, passes=2, air_assist="Yüksek", notes="Ağır hizmet tipi kalın ahşap/MDF.")
        else: # Diyot (Diode)
            if t <= 3.0:
                if power <= 10:
                    return LaserRecommendation(speed_mm_min=180.0, power_percent=95.0, passes=3, air_assist="Güçlü", notes="Düşük güç diyot ile 3mm MDF için çoklu pas gereklidir.")
                else:
                    return LaserRecommendation(speed_mm_min=300.0, power_percent=90.0, passes=2, air_assist="Güçlü", notes="20W+ diyot lazer optimizasyonu.")
            else:
                return LaserRecommendation(speed_mm_min=150.0, power_percent=100.0, passes=4, air_assist="Güçlü", notes="Kalın MDF diyot lazeri zorlar, yavaş ve çok pas ister.")

    # 3. PLEKSİ / AKRİLİK (Acrylic / PMMA)
    elif "pleksi" in mat_name or "akrilik" in mat_name or "acrylic" in mat_name:
        if l_type == "CO2":
            if t <= 3.0:
                if power <= 40:
                    return LaserRecommendation(speed_mm_min=600.0, power_percent=75.0, passes=1, air_assist="Yüksek", notes="Pürüzsüz ve parlak kenar (flame-polished) için ideal.")
                else:
                    return LaserRecommendation(speed_mm_min=1500.0, power_percent=70.0, passes=1, air_assist="Yüksek", notes="Yüksek güçle hızlı pleksi kesimi.")
            else:
                if power <= 50:
                    return LaserRecommendation(speed_mm_min=300.0, power_percent=85.0, passes=1, air_assist="Yüksek", notes="Kalın akrilik, erimeyi önlemek için hava desteği kritik.")
                else:
                    return LaserRecommendation(speed_mm_min=800.0, power_percent=80.0, passes=1, air_assist="Yüksek", notes="Endüstriyel CO2 ile temiz akrilik kenarı.")
        else: # Diyot (Diode)
            return LaserRecommendation(
                speed_mm_min=200.0, power_percent=95.0, passes=3, air_assist="Güçlü",
                notes="⚠ DİKKAT: Mavi diyot (450nm) şeffaf pleksiyi KESemez! Yalnızca siyah veya opak renkli akrilikler kesilebilir."
            )

    # Varsayılan genel emniyetli parametre
    return LaserRecommendation(speed_mm_min=500.0, power_percent=70.0, passes=1, air_assist="Orta", notes="Genel amaçlı varsayılan kesim parametresi.")


def check_aggressive_parameters(rec: LaserRecommendation, laser: Laser) -> List[str]:
    warnings = []
    if rec.power_percent > 90.0:
        warnings.append("Lazer gücü %90 üzerinde; optik lens ve tüp/diyot ömrünü korumak için pas sayısını artırabilirsiniz.")
    if laser.laser_type.upper() in ("DİYOT", "DIYOT"):
        if rec.passes > 3:
            warnings.append("Çoklu pas gerektiren kalın malzeme; işleme süresi uzun olacaktır.")
    return warnings