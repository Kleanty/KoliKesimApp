"""
KoliKesimApp - Kullanıcı Şablonları Motoru (templates.py)

BU DOSYA, geometry.py'DEN TAMAMEN BAĞIMSIZDIR. Amaç: kullanıcının kendi
çizdiği/tanımladığı özel kutu şekillerini (ör. pasta kutusu, dome kapaklı
kutu vb.), FEFCO formüllerinin bulunduğu geometry.py'yi HİÇ DEĞİŞTİRMEDEN
sisteme eklemek.

Neden ayrı dosya?
- geometry.py'deki her fonksiyon TEST EDİLMİŞ, DOĞRULANMIŞ FEFCO formülleri
  içerir. Kullanıcı şablonlarını oraya karıştırmak, yanlışlıkla o kodu
  bozma riski taşır.
- Kullanıcı şablonları burada bile Python KODU değil, JSON VERİSİDİR
  (bkz. user_templates/ klasörü). Yani yeni bir kutu eklemek = yeni bir
  .json dosyası eklemek; hiçbir .py dosyasına dokunulmaz.

Mimari:
    geometry.py      -> FEFCO formülleri (BOX_GENERATORS, generate_flat_pattern)
    templates.py      -> Bu dosya: şablon motoru + JSON okuma/yazma (TEMPLATE_REGISTRY)
    user_templates/*.json -> Sizin çizdiğiniz/tanımladığınız kutular (veri)
    box_factory.py    -> İkisini birleştiren TEK giriş noktası (generate_pattern)

Nasıl çalışır (özet):
    1. Bir kutuyu TEK bir ölçüde (ör. L=300,W=200,H=100) tarif edersiniz:
       her nokta ya SABİT bir sayı ("40") ya da L/W/H'ye bağlı bir formül
       ("L/2", "W - 10") olarak tanımlanır.
    2. Bu tarif bir .json dosyasına yazılır (bkz. user_templates/ örnekleri).
    3. `load_all_templates()` bu klasördeki TÜM .json dosyalarını okuyup
       TEMPLATE_REGISTRY sözlüğüne kaydeder.
    4. `generate_from_template(box, material)` çağrıldığında, formüller
       o anki L/W/H ile yeniden hesaplanır - sabit değerler değişmez,
       formüllü değerler yeni ölçüye göre kayar (resim çerçevesi mantığı).
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .geometry import FlatPattern, Line, LAYER_CUT, LAYER_FOLD, LAYER_MARK, optimize_lines
from .models import BoxParams, Material

Point = Tuple[float, float]

# Kullanıcı şablon dosyalarının (.json) varsayılan klasörü.
DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "user_templates"


# ---------------------------------------------------------------------------
# Güvenli formül hesaplama (AST tabanlı - eval() KULLANILMAZ)
# ---------------------------------------------------------------------------
#
# Şablon dosyaları internetten indirilebilen, güvenilmeyen girdidir. Daha
# önce formüller `eval(..., {"__builtins__": {}})` ile hesaplanıyordu; bu bir
# sandbox DEĞİLDİR (ör. `().__class__.__base__.__subclasses__()` ile kaçış
# mümkündü => keyfi kod çalıştırma). Artık formül ayrıştırılıp yalnızca
# sayı, değişken adı, + - * / // % ** işleçleri ve izin verilen matematik
# fonksiyonu çağrıları kabul edilir; başka her düğüm reddedilir.

_SAFE_FUNCS = {
    "min": min, "max": max, "abs": abs, "round": round,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
}
_SAFE_CONSTS = {"pi": math.pi}

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_FORMULA_LEN = 200
_MAX_POW_EXPONENT = 16


def _eval_node(node, variables: Dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("yalnızca sayısal sabitler kullanılabilir")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in variables:
            return float(variables[node.id])
        if node.id in _SAFE_CONSTS:
            return _SAFE_CONSTS[node.id]
        raise ValueError(f"bilinmeyen değişken: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXPONENT:
            raise ValueError("üs çok büyük")
        return float(_BIN_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return float(_UNARY_OPS[type(node.op)](_eval_node(node.operand, variables)))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _SAFE_FUNCS and not node.keywords):
        args = [_eval_node(a, variables) for a in node.args]
        return float(_SAFE_FUNCS[node.func.id](*args))
    raise ValueError(f"izin verilmeyen ifade: {type(node).__name__}")


def _eval_formula(formula, variables: Dict[str, float]) -> float:
    """Bir formülü (ör. 'L/2 - radius') güvenli biçimde hesaplar.

    `formula` sayısal bir değer (int/float) olarak da verilebilir - bu
    durumda doğrudan sayıya çevrilir (JSON'da hem "40" hem 40 kabul edilir).
    """
    if isinstance(formula, bool):
        raise ValueError(f"Formül hesaplanamadı: '{formula}'")
    if isinstance(formula, (int, float)):
        return float(formula)

    text = str(formula).strip()
    if not text or len(text) > _MAX_FORMULA_LEN:
        raise ValueError(f"Formül hesaplanamadı: '{text[:40]}' -> boş veya çok uzun")
    try:
        tree = ast.parse(text, mode="eval")
        result = _eval_node(tree, variables)
    except Exception as exc:
        raise ValueError(f"Formül hesaplanamadı: '{text}' -> {exc}") from None
    if not math.isfinite(result):
        raise ValueError(f"Formül hesaplanamadı: '{text}' -> sonuç sonlu değil")
    return result


# ---------------------------------------------------------------------------
# Eğri (arc/bezier) yardımcıları
# ---------------------------------------------------------------------------
#
# Shapely/DXF gerçek eğri yerine küçük düz çizgi segmentleri kullanır -
# laser kesim için bu tamamen normaldir.

def _arc_points(cx: float, cy: float, radius: float, start_deg: float, end_deg: float, segments: int = 16) -> List[Point]:
    points = []
    start = math.radians(start_deg)
    end = math.radians(end_deg)
    for i in range(segments + 1):
        t = i / segments
        angle = start + (end - start) * t
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _bezier_points(p0: Point, p1: Point, p2: Point, segments: int = 16) -> List[Point]:
    points = []
    for i in range(segments + 1):
        t = i / segments
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        points.append((x, y))
    return points


# ---------------------------------------------------------------------------
# Şablon veri modeli
# ---------------------------------------------------------------------------

@dataclass
class TemplatePoint:
    """Şablondaki tek bir nokta. x/y birer formül string'idir (ör. 'L/2')."""
    name: str
    x_formula: str
    y_formula: str


@dataclass
class TemplateSegment:
    """İki (line/bezier) veya bir merkez noktası (arc) kullanan tek bir kesim/katlama parçası."""
    kind: str  # "line" | "arc" | "bezier"
    point_names: List[str]
    layer: str = LAYER_CUT
    radius_formula: Optional[str] = None       # yalnızca 'arc' için
    start_angle_deg: Optional[float] = None    # yalnızca 'arc' için
    end_angle_deg: Optional[float] = None      # yalnızca 'arc' için


@dataclass
class ParametricTemplate:
    """Kullanıcının tanımladığı bir kutu şablonu (noktalar + formüller)."""
    name: str
    display_name: str = ""
    parameters: Dict[str, str] = field(default_factory=dict)
    points: List[TemplatePoint] = field(default_factory=list)
    segments: List[TemplateSegment] = field(default_factory=list)

    def _resolve_variables(self, L: float, W: float, H: float, t: float) -> Dict[str, float]:
        variables: Dict[str, float] = {"L": L, "W": W, "H": H, "t": t}
        for key, formula in self.parameters.items():
            variables[key] = _eval_formula(formula, variables)
        return variables

    def evaluate_points(self, L: float, W: float, H: float, t: float) -> Dict[str, Point]:
        variables = self._resolve_variables(L, W, H, t)
        resolved: Dict[str, Point] = {}
        for point in self.points:
            x = _eval_formula(point.x_formula, variables)
            y = _eval_formula(point.y_formula, variables)
            resolved[point.name] = (x, y)
        return resolved

    def to_flat_pattern(self, box: BoxParams, material: Material) -> FlatPattern:
        L, W, H = float(box.length), float(box.width), float(box.height)
        t = max(float(material.thickness), 0.01)

        variables = self._resolve_variables(L, W, H, t)
        resolved_points = self.evaluate_points(L, W, H, t)

        lines: List[Line] = []
        for segment in self.segments:
            if segment.kind == "line":
                p1_name, p2_name = segment.point_names
                lines.append(Line(resolved_points[p1_name], resolved_points[p2_name], segment.layer))

            elif segment.kind == "bezier":
                p0_name, p1_name, p2_name = segment.point_names
                curve = _bezier_points(
                    resolved_points[p0_name], resolved_points[p1_name], resolved_points[p2_name],
                    segments=16,
                )
                for a, b in zip(curve[:-1], curve[1:]):
                    lines.append(Line(a, b, segment.layer))

            elif segment.kind == "arc":
                center_name = segment.point_names[0]
                radius = _eval_formula(segment.radius_formula, variables)
                cx, cy = resolved_points[center_name]
                arc_pts = _arc_points(cx, cy, radius, segment.start_angle_deg, segment.end_angle_deg, segments=16)
                for a, b in zip(arc_pts[:-1], arc_pts[1:]):
                    lines.append(Line(a, b, segment.layer))

            else:
                raise ValueError(f"Bilinmeyen segment tipi: {segment.kind}")

        pattern = FlatPattern(
            lines=optimize_lines(lines),
            box_type=self.name,
            mark_lines=optimize_lines([ln for ln in lines if ln.layer == LAYER_MARK]),
        )
        pattern.update_dimensions()
        return pattern.normalize()


# ---------------------------------------------------------------------------
# JSON <-> ParametricTemplate dönüşümü
# ---------------------------------------------------------------------------

_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_template_name(name) -> str:
    """Şablon adı dosya adı olarak da kullanılır: yol ayırıcı/özel karakter
    (ör. '../x') ve FEFCO kodlarıyla çakışma reddedilir."""
    if not isinstance(name, str) or not _TEMPLATE_NAME_RE.match(name):
        raise ValueError(
            f"Geçersiz şablon adı: {name!r} (yalnızca harf, rakam, '_' ve '-'; en fazla 64 karakter)"
        )
    from .geometry import BOX_GENERATORS
    if name in BOX_GENERATORS:
        raise ValueError(f"Şablon adı yerleşik koli tipiyle çakışıyor: '{name}'")
    return name


def template_from_dict(data: dict) -> ParametricTemplate:
    """Bir JSON (dict) tanımını ParametricTemplate nesnesine çevirir.

    Beklenen JSON şeması için bkz. user_templates/ örnek dosyaları.
    """
    try:
        points = [
            TemplatePoint(name=p["name"], x_formula=p["x"], y_formula=p["y"])
            for p in data["points"]
        ]
        segments = [
            TemplateSegment(
                kind=s["kind"],
                point_names=s["points"],
                layer=s.get("layer", LAYER_CUT),
                radius_formula=s.get("radius"),
                start_angle_deg=s.get("start_angle"),
                end_angle_deg=s.get("end_angle"),
            )
            for s in data["segments"]
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Şablon JSON eksik/bozuk alan içeriyor: {exc}")

    name = validate_template_name(data.get("name"))

    point_names = {p.name for p in points}
    for seg in segments:
        if seg.kind not in ("line", "arc", "bezier"):
            raise ValueError(f"Bilinmeyen segment tipi: {seg.kind}")
        needed = {"line": 2, "bezier": 3, "arc": 1}[seg.kind]
        if len(seg.point_names) != needed:
            raise ValueError(f"'{seg.kind}' segmenti {needed} nokta ister, {len(seg.point_names)} verildi")
        missing = [n for n in seg.point_names if n not in point_names]
        if missing:
            raise ValueError(f"Segment tanımsız nokta kullanıyor: {missing}")
        if seg.kind == "arc" and None in (seg.radius_formula, seg.start_angle_deg, seg.end_angle_deg):
            raise ValueError("'arc' segmenti radius, start_angle ve end_angle ister")

    return ParametricTemplate(
        name=name,
        display_name=data.get("display_name", data["name"]),
        parameters=data.get("parameters", {}),
        points=points,
        segments=segments,
    )


def template_to_dict(template: ParametricTemplate) -> dict:
    """Bir ParametricTemplate nesnesini JSON'a yazılabilir dict'e çevirir."""
    return {
        "name": template.name,
        "display_name": template.display_name or template.name,
        "parameters": template.parameters,
        "points": [
            {"name": p.name, "x": p.x_formula, "y": p.y_formula}
            for p in template.points
        ],
        "segments": [
            {
                "kind": s.kind,
                "points": s.point_names,
                "layer": s.layer,
                **({"radius": s.radius_formula} if s.radius_formula is not None else {}),
                **({"start_angle": s.start_angle_deg} if s.start_angle_deg is not None else {}),
                **({"end_angle": s.end_angle_deg} if s.end_angle_deg is not None else {}),
            }
            for s in template.segments
        ],
    }


def load_template_file(filepath) -> ParametricTemplate:
    """Tek bir .json şablon dosyasını okur."""
    path = Path(filepath)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return template_from_dict(data)


def save_template_file(template: ParametricTemplate, filepath) -> str:
    """Bir şablonu .json dosyasına yazar (kaydet/dışa aktar için)."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template_to_dict(template), f, ensure_ascii=False, indent=2)
    return str(path)


# ---------------------------------------------------------------------------
# Şablon kayıt defteri (registry)
# ---------------------------------------------------------------------------

TEMPLATE_REGISTRY: Dict[str, ParametricTemplate] = {}


def register_template(template: ParametricTemplate) -> None:
    """Bir şablonu kayıt defterine ekler - artık normal bir box_type gibi kullanılabilir."""
    TEMPLATE_REGISTRY[template.name] = template


def load_all_templates(folder=None) -> List[str]:
    """`folder` içindeki TÜM .json dosyalarını okuyup kayıt defterine ekler.

    Hatalı/bozuk bir JSON dosyası, DİĞER şablonların yüklenmesini
    engellemez - sadece o dosya atlanır ve hata mesajı döndürülür.
    Returns: başarıyla yüklenen şablon isimlerinin listesi.
    """
    folder = Path(folder) if folder else DEFAULT_TEMPLATES_DIR
    if not folder.exists():
        return []

    loaded = []
    for json_file in sorted(folder.glob("*.json")):
        try:
            template = load_template_file(json_file)
            register_template(template)
            loaded.append(template.name)
        except Exception as exc:
            print(f"[templates.py] Uyarı: '{json_file.name}' yüklenemedi: {exc}")
    return loaded


def list_template_names() -> List[str]:
    return list(TEMPLATE_REGISTRY.keys())


def generate_from_template(box: BoxParams, material: Material) -> FlatPattern:
    """Kayıtlı bir kullanıcı şablonundan FlatPattern üretir."""
    template = TEMPLATE_REGISTRY.get(box.box_type)
    if template is None:
        raise NotImplementedError(
            f"Kayıtlı şablon bulunamadı: '{box.box_type}'. "
            f"Mevcut şablonlar: {list_template_names()}"
        )
    return template.to_flat_pattern(box, material)
