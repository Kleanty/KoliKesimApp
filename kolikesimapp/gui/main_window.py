import sys
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QDoubleSpinBox,
    QComboBox,
    QPushButton,
    QGroupBox,
    QCheckBox,
    QFileDialog,
    QLineEdit,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QButtonGroup,
    QScrollArea,
    QFrame,
)

from PyQt6.QtGui import (
    QPen,
    QBrush,
    QColor,
    QAction,
    QPainter,
    QTextDocument,
)

from PyQt6.QtCore import Qt, QTimer

from kolikesimapp.core.models import (
    Project,
    BoxParams,
    Material,
    Sheet,
    Laser,
)

from kolikesimapp.core.geometry import (
    LAYER_CUT,
    LAYER_FOLD,
    LAYER_MARK,
)

# NOT: generate_flat_pattern yerine artık box_factory.generate_pattern
# kullanılıyor - bu, hem FEFCO formüllerini (geometry.py) HEM DE
# kullanıcının kendi çizip user_templates/ klasörüne eklediği .json
# şablonlarını (templates.py) tanıyan TEK giriş noktasıdır. geometry.py'nin
# kendisi hâlâ şablonlardan tamamen habersizdir (kasıtlı ayrım).
from kolikesimapp.core.box_factory import (
    generate_pattern,
    available_box_types,
    get_display_name,
    reload_user_templates,
)
from kolikesimapp.core.templates import (
    load_template_file,
    DEFAULT_TEMPLATES_DIR,
)

from kolikesimapp.core.nesting import nest_single_pattern

from kolikesimapp.core.validation import (
    validate_project,
    validate_flat_pattern_fits_sheet,
    check_zero_length_and_duplicate_lines,
    check_overlaps,
    check_sheet_bounds,
    has_errors,
    LEVEL_ERROR,
    LEVEL_WARN,
)

from kolikesimapp.core.laser import (
    recommend_parameters,
    check_aggressive_parameters,
)

from kolikesimapp.core.exporters import export_nested_sheet_to_dxf, export_nested_sheet_to_svg
from kolikesimapp.core.project import save_project, load_project, make_output_folder_name, ensure_unique_folder


class CADGraphicsView(QGraphicsView):
    """Fare tekerleğiyle zoom (yakınlaşma/uzaklaşma) destekleyen özel grafik görünümü"""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        zoom_in_factor = 1.15
        zoom_out_factor = 1.0 / zoom_in_factor
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.lang = "tr"
        self.project = Project()
        self.project.design_mode = "direct_box"

        self.current_pattern = None
        self.current_nesting = None
        self.last_validation_results = []
        self.project_filepath = None

        self.preview_mode = "single"  # "single" veya "sheet"

        self.setWindowTitle("KoliKesimApp - Endüstriyel Koli ve Lazer CAD (CNC Modu)")
        self.resize(1550, 950)

        # Tuşların (up/down butonlarının) net bir şekilde görünmesini sağlayan belirgin QSS Stili.
        # NOT: Qt'nin QSS motoru "image: url(data:...)" base64 gömme biçimini
        # desteklemiyor (test edildi, sessizce hiçbir şey çizmiyor) - bu yüzden
        # onay kutusu tiki, gerçek bir dosya yoluna (assets/checkbox_check.png)
        # referansla yükleniyor; Qt'de url() içinde her zaman "/" kullanılmalı.
        # (f-string DEĞİL - CSS'teki her { } karakterini kaçırmak gerekirdi;
        # bunun yerine tek bir yer tutucu basit .replace() ile değiştiriliyor.)
        checkbox_check_path = (Path(__file__).parent / "assets" / "checkbox_check.png").as_posix()
        self.setStyleSheet("""
            QMainWindow { background-color: #f3f4f6; color: #1f2937; font-family: 'Segoe UI'; }
            QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 6px; margin-top: 10px; padding-top: 14px; background-color: #ffffff; color: #111827; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #111827; }
            QLabel { color: #1f2937; }
            QCheckBox { color: #1f2937; background-color: transparent; font-weight: normal; spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #d1d5db; border-radius: 3px; background-color: #ffffff; }
            QCheckBox::indicator:hover { border-color: #9ca3af; }
            QCheckBox::indicator:checked {
                background-color: #2563eb;
                border-color: #2563eb;
                image: url(__CHECKBOX_CHECK_ICON__);
            }

            QComboBox, QLineEdit { 
                border: 1px solid #cbd5e1; 
                padding: 4px; 
                border-radius: 4px; 
                background-color: #ffffff; 
                color: #1f2937; 
                min-height: 24px; 
            }
            QComboBox:focus, QLineEdit:focus { 
                border: 1px solid #2563eb; 
            }

            QDoubleSpinBox { 
                border: 1px solid #cbd5e1; 
                padding: 4px; 
                padding-right: 24px; 
                border-radius: 4px; 
                background-color: #ffffff; 
                color: #1f2937; 
                min-height: 26px; 
            }
            QDoubleSpinBox:focus { 
                border: 1px solid #2563eb; 
            }
            QDoubleSpinBox::up-button { 
                subcontrol-origin: border; 
                subcontrol-position: top right; 
                width: 22px; 
                border-left: 1px solid #cbd5e1; 
                border-bottom: 1px solid #cbd5e1; 
                border-top-right-radius: 4px; 
                background-color: #e2e8f0; 
            }
            QDoubleSpinBox::up-button:hover { background-color: #cbd5e1; }
            QDoubleSpinBox::down-button { 
                subcontrol-origin: border; 
                subcontrol-position: bottom right; 
                width: 22px; 
                border-left: 1px solid #cbd5e1; 
                border-bottom-right-radius: 4px; 
                background-color: #e2e8f0; 
            }
            QDoubleSpinBox::down-button:hover { background-color: #cbd5e1; }

            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #1f2937;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                border: 1px solid #cbd5e1;
            }

            QPushButton { background-color: #ffffff; border: 1px solid #cbd5e1; padding: 8px; border-radius: 4px; font-weight: bold; color: #374151; }
            QPushButton:hover { background-color: #f9fafb; border-color: #9ca3af; }
            QPushButton#primaryBtn { background-color: #2563eb; color: white; border: none; }
            QPushButton#primaryBtn:hover { background-color: #1d4ed8; }
            QGraphicsView { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; }
        """.replace("__CHECKBOX_CHECK_ICON__", checkbox_check_path))

        self._build_ui()
        self._build_menu()
        self._load_project_into_form()
        self._auto_recalculate()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # =====================================================================
        # 1. SOL PANEL: Birim Sistemi, Koli Tipi (FEFCO), Malzeme ve Lazer
        # =====================================================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.box_group = QGroupBox("Koli Tipi (FEFCO + Özel Şablon) ve İç Ölçüleri (mm)")
        box_form = QFormLayout(self.box_group)
        box_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.box_type_combo = QComboBox()
        for box_type in available_box_types():
            self.box_type_combo.addItem(get_display_name(box_type), box_type)
        self.box_type_combo.currentIndexChanged.connect(self._auto_recalculate)

        self.box_length = QDoubleSpinBox()
        self.box_length.setRange(1, 5000)
        self.box_length.setValue(300)
        self.box_length.setSingleStep(1.0)

        self.box_width = QDoubleSpinBox()
        self.box_width.setRange(1, 5000)
        self.box_width.setValue(200)
        self.box_width.setSingleStep(1.0)

        self.box_height = QDoubleSpinBox()
        self.box_height.setRange(1, 5000)
        self.box_height.setValue(150)
        self.box_height.setSingleStep(1.0)

        for spin in [self.box_length, self.box_width, self.box_height]:
            spin.setSuffix(" mm")
            spin.valueChanged.connect(self._auto_recalculate)

        self.lbl_box_type = QLabel("Koli Modeli:")
        self.lbl_box_length = QLabel("Genişlik / İç En (L):")
        self.lbl_box_width = QLabel("Derinlik / İç Boy (W):")
        self.lbl_box_height = QLabel("Yükseklik (H):")
        box_form.addRow(self.lbl_box_type, self.box_type_combo)
        box_form.addRow(self.lbl_box_length, self.box_length)
        box_form.addRow(self.lbl_box_width, self.box_width)
        box_form.addRow(self.lbl_box_height, self.box_height)
        left_layout.addWidget(self.box_group)

        self.sheet_group = QGroupBox("Malzeme ve Levha Ayarları (mm)")
        sheet_form = QFormLayout(self.sheet_group)
        sheet_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.material_name = QComboBox()
        self.material_name.addItems(
            ["Karton", "Mukavva", "Oluklu Karton (E-Flute)", "Oluklu Karton (B-Flute)", "Oluklu Karton (C-Flute)",
             "MDF", "Pleksi"])

        self.material_thickness = QDoubleSpinBox()
        self.material_thickness.setRange(0.1, 50)
        self.material_thickness.setValue(3.0)
        self.material_thickness.setSingleStep(0.5)
        self.material_thickness.setSuffix(" mm")

        self.sheet_width = QDoubleSpinBox()
        self.sheet_width.setRange(10, 10000)
        self.sheet_width.setValue(1000)
        self.sheet_width.setSingleStep(10.0)
        self.sheet_width.setSuffix(" mm")

        self.sheet_height = QDoubleSpinBox()
        self.sheet_height.setRange(10, 10000)
        self.sheet_height.setValue(2000)
        self.sheet_height.setSingleStep(10.0)
        self.sheet_height.setSuffix(" mm")

        self.sheet_margin = QDoubleSpinBox()
        self.sheet_margin.setRange(0, 100)
        self.sheet_margin.setValue(5.0)
        self.sheet_margin.setSingleStep(1.0)
        self.sheet_margin.setSuffix(" mm")

        self.sheet_spacing = QDoubleSpinBox()
        self.sheet_spacing.setRange(0, 100)
        self.sheet_spacing.setValue(5.0)
        self.sheet_spacing.setSingleStep(1.0)
        self.sheet_spacing.setSuffix(" mm")

        for widget in [self.material_name, self.material_thickness, self.sheet_width, self.sheet_height,
                       self.sheet_margin, self.sheet_spacing]:
            if isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self._auto_recalculate)
            else:
                widget.currentIndexChanged.connect(self._auto_recalculate)

        self.lbl_material_name = QLabel("Malzeme Türü:")
        self.lbl_material_thickness = QLabel("Kalınlık (t):")
        self.lbl_sheet_width = QLabel("Levha Genişliği:")
        self.lbl_sheet_height = QLabel("Levha Yüksekliği:")
        self.lbl_sheet_margin = QLabel("Kenar Boşluğu:")
        self.lbl_sheet_spacing = QLabel("Parça Boşluğu:")
        sheet_form.addRow(self.lbl_material_name, self.material_name)
        sheet_form.addRow(self.lbl_material_thickness, self.material_thickness)
        sheet_form.addRow(self.lbl_sheet_width, self.sheet_width)
        sheet_form.addRow(self.lbl_sheet_height, self.sheet_height)
        sheet_form.addRow(self.lbl_sheet_margin, self.sheet_margin)
        sheet_form.addRow(self.lbl_sheet_spacing, self.sheet_spacing)
        left_layout.addWidget(self.sheet_group)

        self.laser_group = QGroupBox("Lazer ve Kesim Parametreleri")
        laser_form = QFormLayout(self.laser_group)
        laser_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.laser_type_combo = QComboBox()
        self.laser_type_combo.addItems(["CO2", "Diyot"])
        self.laser_type_combo.currentIndexChanged.connect(self._auto_recalculate)

        self.laser_power = QDoubleSpinBox()
        self.laser_power.setRange(1, 2000)
        self.laser_power.setValue(40.0)
        self.laser_power.setSingleStep(5.0)
        self.laser_power.setSuffix(" W")
        self.laser_power.valueChanged.connect(self._auto_recalculate)

        self.lbl_laser_type = QLabel("Lazer Türü:")
        self.lbl_laser_power = QLabel("Lazer Gücü:")
        laser_form.addRow(self.lbl_laser_type, self.laser_type_combo)
        laser_form.addRow(self.lbl_laser_power, self.laser_power)

        self.laser_recommendation_label = QLabel("Öneri bekleniyor...")
        self.laser_recommendation_label.setWordWrap(True)
        self.laser_recommendation_label.setStyleSheet(
            "color: #4b5563; font-size: 11px; background-color: #f9fafb; padding: 6px; border-radius: 4px;")
        laser_form.addRow(self.laser_recommendation_label)

        left_layout.addWidget(self.laser_group)
        left_layout.addStretch(1)
        splitter.addWidget(left_widget)

        # =====================================================================
        # 2. ORTA PANEL: 2D Teknik Çizim Önizleme ve Lejant (Zoom Özellikli)
        # =====================================================================
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)

        mode_header_layout = QHBoxLayout()
        self.preview_header_lbl = QLabel("2D Teknik CAD Önizleme (Tekerlekle Zoom Yapabilirsiniz)")
        self.preview_header_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #374151;")
        mode_header_layout.addWidget(self.preview_header_lbl)
        mode_header_layout.addStretch(1)

        self.btn_view_single = QPushButton("Tek Koli Açınımı")
        self.btn_view_single.setCheckable(True)
        self.btn_view_single.setChecked(True)

        self.btn_view_sheet = QPushButton("Komple Levha (Nesting Yerleşimi)")
        self.btn_view_sheet.setCheckable(True)

        self.preview_mode_group = QButtonGroup(self)
        self.preview_mode_group.addButton(self.btn_view_single, 0)
        self.preview_mode_group.addButton(self.btn_view_sheet, 1)
        self.preview_mode_group.buttonClicked.connect(self._on_preview_mode_changed)

        mode_header_layout.addWidget(self.btn_view_single)
        mode_header_layout.addWidget(self.btn_view_sheet)
        center_layout.addLayout(mode_header_layout)

        preview_container = QWidget()
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)

        self.scene = QGraphicsScene()
        self.view = CADGraphicsView(self.scene)
        preview_container_layout.addWidget(self.view)

        center_layout.addWidget(preview_container, 1)

        self.legend_label = QLabel(
            "<b>CNC Katman Lejantı:</b><br>"
            "<font color='#dc2626'>■</font> <b>Kırmızı (Dış Kesim - Cut):</b> Lazer %100 Kesim<br>"
            "<font color='#2563eb'>■</font> <b>Mavi (Kırım/Katlama - Fold):</b> Pilyaj / Oluk Çizgisi<br>"
            "<font color='#16a34a'>■</font> <b>Yeşil (Markalama - Mark):</b> Pozisyon / Yazı Markalama"
        )
        self.legend_label.setStyleSheet("""
            background-color: rgba(255, 255, 255, 230);
            border: 1px solid #d1d5db;
            border-radius: 4px;
            padding: 6px;
            font-size: 11px;
            color: #1f2937;
        """)
        # setWordWrap olmadan, dar bir maksimum genişlikte uzun satırlar
        # (ör. "Yeşil (Markalama - Mark): Pozisyon / Yazı Markalama") kutunun
        # sınırının dışına taşıp kesik görünüyordu. Hem sarmalama açıldı hem
        # de genişlik, metnin rahatça sığması için biraz artırıldı.
        self.legend_label.setWordWrap(True)
        self.legend_label.setMinimumWidth(300)
        self.legend_label.setMaximumWidth(320)

        legend_row = QHBoxLayout()
        legend_row.addWidget(self.legend_label)
        legend_row.addStretch(1)
        center_layout.addLayout(legend_row)

        splitter.addWidget(center_widget)

        # =====================================================================
        # 3. SAĞ PANEL: Güvenlik Kontrolleri, Üretim Özeti ve DXF/SVG Çıktı
        # =====================================================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.control_group = QGroupBox("Tasarım Güvenlik Kontrolleri")
        control_layout = QVBoxLayout(self.control_group)
        self.checks_container = QWidget()
        self.checks_layout = QVBoxLayout(self.checks_container)
        self.checks_layout.setContentsMargins(0, 0, 0, 0)
        self.checks_layout.setSpacing(4)

        # ÖNEMLİ: Kontrol mesajları (özellikle uzun, sarmalanan hata
        # metinleri) doğrudan bir QSplitter altındaki QVBoxLayout'a
        # eklendiğinde, Qt kelime-sarmalı QLabel'ların gerçek (sarmalanmış)
        # yüksekliğini hesaba katmıyor (height-for-width, QSplitter içinde
        # güvenilir şekilde yayılmıyor) - bu da üst üste binen, okunamaz
        # satırlara yol açıyordu (ekran görüntüsüyle tespit edildi). Bunu
        # bir QScrollArea içine almak, her genişlik değişiminde içeriğin
        # gerçek boyutuyla yeniden düzenlenmesini garanti eder; ayrıca çok
        # sayıda hata/uyarı olduğunda panel sonsuza kadar büyümez, kaydırılır.
        self.checks_scroll = QScrollArea()
        self.checks_scroll.setWidgetResizable(True)
        self.checks_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.checks_scroll.setWidget(self.checks_container)
        # Tipik durumda (çoğu kontrol tek satır, ~9-10 kontrol) kaydırmaya
        # gerek kalmadan hepsi görünsün diye yeterince yüksek; yalnızca çok
        # sayıda/uzun hata mesajı varsa (bkz. yukarıdaki not) kaydırmaya döner.
        self.checks_scroll.setMaximumHeight(340)
        control_layout.addWidget(self.checks_scroll)
        right_layout.addWidget(self.control_group)

        self.summary_group = QGroupBox("Üretim Özeti && Sonuçlar")
        summary_layout = QVBoxLayout(self.summary_group)
        self.summary_label = QLabel("Hesaplama bekleniyor...")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        right_layout.addWidget(self.summary_group)

        right_layout.addStretch(1)

        self.output_group = QGroupBox("CNC / CAD Çıktı Ayarları")
        output_layout = QVBoxLayout(self.output_group)

        self.sheet_outline_checkbox = QCheckBox("Levha sınırını DXF/SVG dosyasına ekle")
        self.sheet_outline_checkbox.setChecked(True)
        output_layout.addWidget(self.sheet_outline_checkbox)

        folder_row = QHBoxLayout()
        self.output_folder_edit = QLineEdit(str(Path.home() / "Koli_CNC_Projeleri"))
        self.choose_folder_button = QPushButton("Klasör Seç")
        self.choose_folder_button.clicked.connect(self._choose_output_folder)
        folder_row.addWidget(self.output_folder_edit, 1)
        folder_row.addWidget(self.choose_folder_button)
        output_layout.addLayout(folder_row)

        btn_row = QHBoxLayout()
        self.generate_dxf_button = QPushButton("DXF İndir")
        self.generate_dxf_button.setObjectName("primaryBtn")
        self.generate_dxf_button.clicked.connect(self._on_generate_dxf)

        self.generate_svg_button = QPushButton("SVG İndir")
        self.generate_svg_button.clicked.connect(self._on_generate_svg)

        btn_row.addWidget(self.generate_dxf_button)
        btn_row.addWidget(self.generate_svg_button)
        output_layout.addLayout(btn_row)

        right_layout.addWidget(self.output_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([420, 680, 400])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_menu(self):
        menubar = self.menuBar()

        self.file_menu = menubar.addMenu("Dosya")
        file_menu = self.file_menu
        self.action_new = QAction("Yeni Proje", self)
        self.action_open = QAction("Proje Aç...", self)
        self.action_save = QAction("Kaydet", self)
        self.action_save_as = QAction("Farklı Kaydet...", self)

        self.action_new.triggered.connect(self._new_project)
        self.action_open.triggered.connect(self._open_project)
        self.action_save.triggered.connect(self._save_project)
        self.action_save_as.triggered.connect(self._save_project_as)

        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)

        lang_menu = menubar.addMenu("Dil / Language")
        self.action_tr = QAction("Türkçe", self)
        self.action_en = QAction("English", self)
        self.action_tr.triggered.connect(lambda: self._set_language("tr"))
        self.action_en.triggered.connect(lambda: self._set_language("en"))
        lang_menu.addAction(self.action_tr)
        lang_menu.addAction(self.action_en)

        # --- Şablonlar menüsü: kullanıcının kendi çizdiği .json kutuları ---
        self.templates_menu = menubar.addMenu("Şablonlar")
        templates_menu = self.templates_menu
        self.action_load_template = QAction("Şablon Yükle...", self)
        self.action_reload_templates = QAction("Şablonları Yeniden Tara", self)
        self.action_load_template.triggered.connect(self._on_load_template)
        self.action_reload_templates.triggered.connect(self._on_reload_templates)
        templates_menu.addAction(self.action_load_template)
        templates_menu.addAction(self.action_reload_templates)

    def _refresh_box_type_combo(self, select_box_type=None):
        """Koli tipi listesini (FEFCO + kullanıcı şablonları) yeniden doldurur.

        `select_box_type` verilirse, yeniden doldurma sonrası o tip
        seçili hale getirilir (yeni yüklenen şablonu otomatik seçmek için).
        """
        current = select_box_type or self.box_type_combo.currentData()
        self.box_type_combo.blockSignals(True)
        self.box_type_combo.clear()
        for box_type in available_box_types():
            self.box_type_combo.addItem(get_display_name(box_type), box_type)
        idx = self.box_type_combo.findData(current)
        self.box_type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.box_type_combo.blockSignals(False)

    def _on_load_template(self):
        """Kullanıcının bilgisayarındaki bir .json şablon dosyasını seçtirir,
        doğrular, user_templates/ klasörüne kopyalar ve listeye ekler.

        Neden "kopyala" (taşı değil)? Kullanıcının orijinal dosyası nerede
        olursa olsun dursun; uygulama kendi klasöründe kalıcı bir kopya
        tutar - böylece orijinal dosya silinse/taşınsa bile şablon çalışmaya
        devam eder.
        """
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Şablon Yükle (.json)", "", "JSON Şablonu (*.json)"
        )
        if not filepath:
            return

        try:
            # 1) Önce DOĞRULA - bozuk/eksik bir dosya asla klasöre kopyalanmaz
            template = load_template_file(filepath)
        except Exception as exc:
            QMessageBox.critical(
                self, "Şablon Hatası",
                f"Bu dosya geçerli bir şablon değil:\n\n{exc}\n\n"
                f"Beklenen format için user_templates/demo_rounded.json örneğine bakın."
            )
            return

        # 2) Hedef klasöre kopyala (aynı isimde bir dosya varsa üzerine yazmadan önce sor)
        DEFAULT_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        destination = DEFAULT_TEMPLATES_DIR / f"{template.name}.json"
        if destination.exists():
            reply = QMessageBox.question(
                self, "Üzerine Yaz mı?",
                f"'{template.name}' adında bir şablon zaten var. Üzerine yazılsın mı?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        import shutil
        try:
            shutil.copyfile(filepath, destination)
        except OSError as exc:
            QMessageBox.critical(self, "Şablon Hatası", f"Şablon kopyalanamadı:\n\n{exc}")
            return

        # 3) Kayıt defterini tazele ve yeni şablonu listede seçili yap
        reload_user_templates()
        self._refresh_box_type_combo(select_box_type=template.name)
        self._auto_recalculate()

        QMessageBox.information(
            self, "Şablon Yüklendi",
            f"'{template.display_name or template.name}' başarıyla yüklendi ve seçildi."
        )

    def _on_reload_templates(self):
        """user_templates/ klasörünü yeniden tarar - dosya gezgininden elle
        kopyalanan yeni .json dosyalarının, uygulamayı yeniden başlatmadan
        listeye görünmesini sağlar."""
        loaded = reload_user_templates()
        self._refresh_box_type_combo()
        QMessageBox.information(
            self, "Şablonlar Tarandı",
            f"{len(loaded)} kullanıcı şablonu yüklendi:\n" + "\n".join(loaded) if loaded
            else "user_templates/ klasöründe .json şablon bulunamadı."
        )

    def _set_language(self, lang_code):
        self.lang = lang_code
        if lang_code == "en":
            self.setWindowTitle("BoxCuttingApp - Industrial Box and Laser CAD (CNC Mode)")
            self.box_group.setTitle("Box Type (FEFCO + Custom Template) && Dimensions (mm)")
            self.sheet_group.setTitle("Material && Sheet Settings (mm)")
            self.laser_group.setTitle("Laser && Cutting Parameters")
            self.control_group.setTitle("Design Safety Checks")
            self.summary_group.setTitle("Production Summary && Results")
            self.output_group.setTitle("CNC / CAD Output Settings")
            self.btn_view_single.setText("Single Box Unfold")
            self.btn_view_sheet.setText("Full Sheet (Nesting Layout)")
            self.sheet_outline_checkbox.setText("Include sheet outline in DXF/SVG")
            self.choose_folder_button.setText("Select Folder")
            self.generate_dxf_button.setText("Download DXF")
            self.generate_svg_button.setText("Download SVG")
            self.preview_header_lbl.setText("2D Technical CAD Preview (Scroll Wheel to Zoom)")

            self.lbl_box_type.setText("Box Model:")
            self.lbl_box_length.setText("Width / Internal L (L):")
            self.lbl_box_width.setText("Depth / Internal W (W):")
            self.lbl_box_height.setText("Height (H):")
            self.lbl_material_name.setText("Material Type:")
            self.lbl_material_thickness.setText("Thickness (t):")
            self.lbl_sheet_width.setText("Sheet Width:")
            self.lbl_sheet_height.setText("Sheet Height:")
            self.lbl_sheet_margin.setText("Edge Margin:")
            self.lbl_sheet_spacing.setText("Part Spacing:")
            self.lbl_laser_type.setText("Laser Type:")
            self.lbl_laser_power.setText("Laser Power:")

            self.file_menu.setTitle("File")
            self.action_new.setText("New Project")
            self.action_open.setText("Open Project...")
            self.action_save.setText("Save")
            self.action_save_as.setText("Save As...")
            self.templates_menu.setTitle("Templates")
            self.action_load_template.setText("Load Template...")
            self.action_reload_templates.setText("Rescan Templates")

            self.status_bar.showMessage("Language switched to English.")
        else:
            self.setWindowTitle("KoliKesimApp - Endüstriyel Koli ve Lazer CAD (CNC Modu)")
            self.box_group.setTitle("Koli Tipi (FEFCO + Özel Şablon) ve İç Ölçüleri (mm)")
            self.sheet_group.setTitle("Malzeme ve Levha Ayarları (mm)")
            self.laser_group.setTitle("Lazer ve Kesim Parametreleri")
            self.control_group.setTitle("Tasarım Güvenlik Kontrolleri")
            self.summary_group.setTitle("Üretim Özeti && Sonuçlar")
            self.output_group.setTitle("CNC / CAD Çıktı Ayarları")
            self.btn_view_single.setText("Tek Koli Açınımı")
            self.btn_view_sheet.setText("Komple Levha (Nesting Yerleşimi)")
            self.sheet_outline_checkbox.setText("Levha sınırını DXF/SVG dosyasına ekle")
            self.choose_folder_button.setText("Klasör Seç")
            self.generate_dxf_button.setText("DXF İndir")
            self.generate_svg_button.setText("SVG İndir")
            self.preview_header_lbl.setText("2D Teknik CAD Önizleme (Tekerlekle Zoom Yapabilirsiniz)")

            self.lbl_box_type.setText("Koli Modeli:")
            self.lbl_box_length.setText("Genişlik / İç En (L):")
            self.lbl_box_width.setText("Derinlik / İç Boy (W):")
            self.lbl_box_height.setText("Yükseklik (H):")
            self.lbl_material_name.setText("Malzeme Türü:")
            self.lbl_material_thickness.setText("Kalınlık (t):")
            self.lbl_sheet_width.setText("Levha Genişliği:")
            self.lbl_sheet_height.setText("Levha Yüksekliği:")
            self.lbl_sheet_margin.setText("Kenar Boşluğu:")
            self.lbl_sheet_spacing.setText("Parça Boşluğu:")
            self.lbl_laser_type.setText("Lazer Türü:")
            self.lbl_laser_power.setText("Lazer Gücü:")

            self.file_menu.setTitle("Dosya")
            self.action_new.setText("Yeni Proje")
            self.action_open.setText("Proje Aç...")
            self.action_save.setText("Kaydet")
            self.action_save_as.setText("Farklı Kaydet...")
            self.templates_menu.setTitle("Şablonlar")
            self.action_load_template.setText("Şablon Yükle...")
            self.action_reload_templates.setText("Şablonları Yeniden Tara")

            self.status_bar.showMessage("Dil Türkçe olarak ayarlandı.")

        # Özet paneli ve lazer önerisi metinleri de dile göre üretildiği için
        # (bkz. _update_summary / _auto_recalculate), dil değişince ekranda
        # hâlâ eski dilde görünmemeleri için hemen yeniden hesaplatıyoruz.
        self._auto_recalculate()

    def _on_preview_mode_changed(self, button):
        if button == self.btn_view_single:
            self.preview_mode = "single"
        else:
            self.preview_mode = "sheet"
        self._update_preview()

    def _update_preview(self):
        if self.preview_mode == "single":
            if self.current_pattern is not None:
                self._draw_single_pattern(self.current_pattern)
            else:
                self.scene.clear()
        else:
            if self.current_pattern is not None and self.current_nesting is not None:
                self._draw_nested_preview()
            else:
                self.scene.clear()

    def _auto_recalculate(self):
        try:
            project = self._collect_project()

            rec = recommend_parameters(project.laser, project.material)
            if rec:
                warnings = check_aggressive_parameters(rec, project.laser)
                if self.lang == "tr":
                    warn_text = f" | Risk: {len(warnings)}" if warnings else ""
                    self.laser_recommendation_label.setText(
                        f"💡 <b>Lazer Önerisi:</b> Hız: {rec.speed_mm_min} mm/dk | "
                        f"Güç: %{rec.power_percent} | Pass: {rec.passes}{warn_text}"
                    )
                else:
                    warn_text = f" | Risk: {len(warnings)}" if warnings else ""
                    self.laser_recommendation_label.setText(
                        f"💡 <b>Laser Recommendation:</b> Speed: {rec.speed_mm_min} mm/min | "
                        f"Power: %{rec.power_percent} | Pass: {rec.passes}{warn_text}"
                    )
            else:
                self.laser_recommendation_label.setText(
                    "⚠ Bu kombinasyon için veri tabanında öneri yok." if self.lang == "tr"
                    else "⚠ No recommendation in the database for this combination."
                )

            pattern = generate_pattern(project.box, project.material)
            self.current_pattern = pattern

            nesting = nest_single_pattern(pattern.width, pattern.height, project.sheet)
            self.current_nesting = nesting

            results = validate_project(project)
            results += validate_flat_pattern_fits_sheet(pattern, project.sheet.width, project.sheet.height,
                                                        project.sheet.margin)
            results += check_zero_length_and_duplicate_lines(pattern)
            results += check_overlaps(nesting)
            results += check_sheet_bounds(nesting, project.sheet.width, project.sheet.height, project.sheet.margin)

            self.last_validation_results = results
            self._render_validation_results(results)

            self._update_preview()
            self._update_summary(project, results)

            if has_errors(results):
                self.status_bar.showMessage("Uyarı: Tasarımda hatalar veya levha dışına taşma tespit edildi!")
            else:
                self.status_bar.showMessage(
                    "Tasarım kontrollerinden geçti (gerçek kesimden önce test kesimi önerilir)."
                    if self.lang == "tr" else "Design passed checks (a test cut is still recommended before production)."
                )

        except Exception as exc:
            # Hesaplama başarısız oldu - eski (artık geçerli formla eşleşmeyen)
            # açınımı/nesting'i ORTADA BIRAKMAK TEHLİKELİ: kullanıcı farkında
            # olmadan "DXF İndir"e basarsa, ekrandaki güncel ayarlarla eşleşmeyen
            # ESKİ bir dosya sessizce üretilebilir. Bu yüzden geçersiz duruma
            # düşen her şeyi açıkça temizliyoruz.
            self.current_pattern = None
            self.current_nesting = None
            self.last_validation_results = []
            self.scene.clear()
            self.summary_label.setText(f"⚠ Hesaplama hatası: {exc}")
            self.status_bar.showMessage(f"Hesaplama Hatası: {str(exc)}")

    def _render_validation_results(self, results):
        # GERÇEK KÖK NEDEN (bkz. REGRESSION): __init__ sırasında birden çok
        # alan (box_length, box_width, ... spin box'ları) değer atanırken
        # valueChanged sinyali tetikleniyor ve HENÜZ olay döngüsü hiç
        # dönmeden _auto_recalculate() art arda birkaç kez senkron olarak
        # çağrılıyor. `deleteLater()` silmeyi yalnızca ERTELER (olay
        # döngüsü bir sonraki turunda gerçekleşir); bu yüzden önceki
        # "nesil"lerin etiketleri, layout'tan çıkarılmış olsalar bile hâlâ
        # checks_container'ın GÖRÜNÜR çocukları olarak kalıp eski
        # konumlarında çizilmeye devam ediyordu - ekranda görülen üst üste
        # binme/karma metin, aslında birden fazla hâlâ-canlı etiketin aynı
        # alanda üst üste çizilmesiydi. Çözüm: deleteLater() ile sıraya
        # koymadan ÖNCE setParent(None) ile widget'ı HEMEN görünür
        # ağaçtan kopar - bu, olay döngüsü beklemeden anında etkili olur.
        while self.checks_layout.count():
            item = self.checks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # item.widget() yalnızca BİR KEZ okunuyor: setParent(None)
                # çağrısından sonra item.widget() tekrar sorgulanırsa None
                # dönebiliyor (test ederken bu şekilde çökme yakalandı).
                widget.setParent(None)
                widget.deleteLater()

        # ÖNEMLİ (bkz. REGRESSION): Kelime-sarmalı (setWordWrap(True)) bir
        # QLabel'ın gerçek (sarmalanmış) yüksekliği, QVBoxLayout tarafından
        # güvenilir şekilde hesaplanmıyor - QScrollArea/QSplitter gibi iç
        # içe geçmiş düzenler altında sizeHint() genellikle NİHAİ genişlik
        # belli olmadan sorgulanıyor, bu da satırların üst üste binmesine
        # yol açıyordu (ekran görüntüsüyle iki ayrı kez tespit edildi).
        # Çözüm: her etiketin yüksekliğini, GERÇEK kullanılabilir genişliğe
        # göre `heightForWidth()` ile KENDİMİZ hesaplayıp minimum yükseklik
        # olarak sabitliyoruz - böylece layout'un güvenilmez otomatik
        # hesabına bağımlı kalmıyoruz.
        wrap_width = self.checks_scroll.viewport().width()
        if wrap_width <= 0:
            # Henüz ilk kez gösterilmeden önce (örn. __init__ sırasında)
            # viewport genişliği 0 olabilir; panel genişliğine yakın makul
            # bir varsayılan kullanılır, pencere gösterildikten sonraki ilk
            # yeniden hesaplamada doğru genişlikle tekrar düzeltilir.
            wrap_width = 360
        # İKİNCİ bir ince tuzak: içerik 340px sınırını aşınca dikey kaydırma
        # çubuğu BELİRİYOR ve viewport'u ~16-20px daraltıyor - ama bu ölçüm
        # tam da o kaydırma çubuğunun görünüp görünmeyeceği belli olmadan
        # yapılıyor (döngüsel bağımlılık). Bir satırın "tam sığıyor"
        # sanılıp tek satır yüksekliği kilitlenmesi, sonra kaydırma çubuğu
        # belirince gerçekte iki satıra sarması (ve bir alttaki satırın
        # üstüne binmesi) tam olarak tespit edilen hataydı. Güvenli tarafta
        # kalmak için kaydırma çubuğu payını HER ZAMAN düş: gerekenden
        # fazla yükseklik ayırmak, üst üste binmekten iyidir.
        wrap_width = max(wrap_width - 24, 120)

        # DAHA ÖNCEKİ (BAŞARISIZ) YAKLAŞIM: satır yüksekliklerini kendimiz
        # doğru hesaplayıp setMinimumHeight() ile sabitledik, ama ardından
        # dış QScrollArea'nın yüksekliğini checks_container.sizeHint() ile
        # belirledik - bu da etiketlerin DOĞRU minimumHeight'larını hesaba
        # katmıyordu (sizeHint, minimumHeight'tan bağımsız bir değer).
        # Sonuç: dış kutu gerekenden daha KISA sabitlendi, ardından
        # QVBoxLayout mevcut (yetersiz) alana sığmak için etiketleri kendi
        # minimumHeight'larının bile ALTINA sıkıştırdı - üst üste binme bu
        # yüzden sürüyordu. Çözüm: Qt'nin herhangi bir sizeHint/heightForWidth
        # hesaplamasına ikinci kez güvenmek yerine, gereken toplam yüksekliği
        # BURADA, kendi hesapladığımız değerlerden doğrudan topluyoruz.
        total_height = 0
        spacing = self.checks_layout.spacing()

        for res in results:
            if res.level == LEVEL_ERROR:
                prefix, color = "✕", "#dc2626"
            elif res.level == LEVEL_WARN:
                prefix, color = "⚠", "#d97706"
            else:
                prefix, color = "✓", "#16a34a"

            html = f"<span style='color: {color}; font-weight: bold;'>{prefix}</span> <span style='color: #1f2937;'>{res.message}</span>"
            lbl = QLabel(html)
            lbl.setWordWrap(True)

            # lbl.heightForWidth() güvenilmez çıktı (QLabel'ın iç rich-text
            # belgesi henüz hiç çizilmediği/boyutlanmadığı için muhtemelen
            # yanlış/varsayılan bir değer veriyor). Bunun yerine, AYNI HTML
            # içeriğini bağımsız bir QTextDocument'e verip onun gerçek
            # sarmalanmış yüksekliğini soruyoruz - bu, QLabel'ın perde
            # arkasında kullandığı mekanizmanın ta kendisi ve widget'ın
            # gösterilip gösterilmediğinden bağımsız, her zaman doğru sonuç
            # veriyor.
            doc = QTextDocument()
            doc.setDefaultFont(lbl.font())
            doc.setHtml(html)
            doc.setTextWidth(wrap_width)
            needed_height = int(doc.size().height()) + 4
            lbl.setMinimumHeight(needed_height)

            self.checks_layout.addWidget(lbl)
            total_height += needed_height + spacing

        self._checks_total_content_height = total_height
        # Qt bir sonraki olay döngüsünde genişlikleri netleştirdikten SONRA
        # dış kaydırma kutusunu bu (kendi hesapladığımız, güvenilir) toplam
        # yüksekliğe göre boyutlandırıyoruz.
        QTimer.singleShot(0, self._resize_checks_scroll_to_content)

    def _resize_checks_scroll_to_content(self):
        self.checks_layout.activate()
        content_height = getattr(self, "_checks_total_content_height", 0)
        self.checks_scroll.setFixedHeight(min(max(content_height + 8, 40), 340))

    def _collect_project(self):
        # Uygulama artık yalnızca mm kullanıyor (tek birim) - form
        # alanlarındaki değerler zaten mm, dönüşüm gerekmiyor.
        thickness = self.material_thickness.value()
        auto_clearance = max(2.0, round(thickness * 1.5, 1))

        self.project.box = BoxParams(
            box_type=self.box_type_combo.currentData(),
            length=self.box_length.value(),
            width=self.box_width.value(),
            height=self.box_height.value(),
            minor_flap_clearance=auto_clearance,
        )
        self.project.material = Material(
            name=self.material_name.currentText(),
            thickness=thickness,
        )
        self.project.sheet = Sheet(
            width=self.sheet_width.value(),
            height=self.sheet_height.value(),
            margin=self.sheet_margin.value(),
            spacing=self.sheet_spacing.value(),
        )
        self.project.laser = Laser(
            laser_type=self.laser_type_combo.currentText(),
            power_watt=self.laser_power.value(),
        )
        return self.project

    def _load_project_into_form(self):
        p = self.project

        idx = self.box_type_combo.findData(p.box.box_type)
        if idx >= 0:
            self.box_type_combo.setCurrentIndex(idx)
        else:
            # Sessizce başka bir koli tipinde bırakmak yanlış geometriye yol açar.
            QMessageBox.warning(
                self, "Bilinmeyen Koli Tipi",
                f"Projedeki koli tipi '{p.box.box_type}' bu kurulumda yok "
                f"(silinmiş bir kullanıcı şablonu olabilir). Formda şu an seçili olan tip "
                f"korundu; lütfen koli tipini kontrol edin.")

        self.box_length.setValue(p.box.length)
        self.box_width.setValue(p.box.width)
        self.box_height.setValue(p.box.height)

        self.material_thickness.setValue(p.material.thickness)
        self.sheet_width.setValue(p.sheet.width)
        self.sheet_height.setValue(p.sheet.height)
        self.sheet_margin.setValue(p.sheet.margin)
        self.sheet_spacing.setValue(p.sheet.spacing)

        laser_idx = self.laser_type_combo.findText(p.laser.laser_type)
        if laser_idx >= 0: self.laser_type_combo.setCurrentIndex(laser_idx)
        self.laser_power.setValue(p.laser.power_watt)

    def _draw_single_pattern(self, pattern):
        self.scene.clear()
        self.scene.setBackgroundBrush(QColor("#f9fafb"))

        for line in pattern.lines:
            if line.layer == LAYER_CUT:
                color, style, width = QColor("#dc2626"), Qt.PenStyle.SolidLine, 1.6
            elif line.layer == LAYER_FOLD:
                color, style, width = QColor("#2563eb"), Qt.PenStyle.DashLine, 1.4
            elif line.layer == LAYER_MARK:
                color, style, width = QColor("#16a34a"), Qt.PenStyle.DotLine, 1.4
            else:
                continue

            pen = QPen(color)
            pen.setWidthF(width)
            pen.setStyle(style)
            item = QGraphicsLineItem(line.p1[0], -line.p1[1], line.p2[0], -line.p2[1])
            item.setPen(pen)
            self.scene.addItem(item)

        bounds = self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        self.scene.setSceneRect(bounds)
        self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_nested_preview(self):
        if self.current_pattern is None or self.current_nesting is None:
            return

        pattern = self.current_pattern
        nesting = self.current_nesting
        project = self.project

        self.scene.clear()
        self.scene.setBackgroundBrush(QColor("#f9fafb"))

        sheet_pen = QPen(QColor("#9ca3af"))
        sheet_pen.setWidthF(2.0)
        sheet_rect = QGraphicsRectItem(0, -project.sheet.height, project.sheet.width,
                                       project.sheet.height)
        sheet_rect.setPen(sheet_pen)
        sheet_rect.setBrush(QBrush(QColor("#ffffff")))
        self.scene.addItem(sheet_rect)

        for placement in nesting.placements:
            for line in pattern.lines:
                p1, p2 = line.p1, line.p2
                if placement.rotated:
                    p1 = (p1[1], pattern.width - p1[0])
                    p2 = (p2[1], pattern.width - p2[0])

                x1, y1 = (p1[0] + placement.x), -((p1[1] + placement.y))
                x2, y2 = (p2[0] + placement.x), -((p2[1] + placement.y))

                if line.layer == LAYER_CUT:
                    color, style, width = QColor("#dc2626"), Qt.PenStyle.SolidLine, 1.5
                elif line.layer == LAYER_FOLD:
                    color, style, width = QColor("#2563eb"), Qt.PenStyle.DashLine, 1.3
                elif line.layer == LAYER_MARK:
                    color, style, width = QColor("#16a34a"), Qt.PenStyle.DotLine, 1.3
                else:
                    continue

                pen = QPen(color)
                pen.setWidthF(width)
                pen.setStyle(style)
                item = QGraphicsLineItem(x1, y1, x2, y2)
                item.setPen(pen)
                self.scene.addItem(item)

        bounds = self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        self.scene.setSceneRect(bounds)
        self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _update_summary(self, project, results):
        error_count = sum(1 for r in results if r.level == LEVEL_ERROR)
        tr = self.lang == "tr"

        if tr:
            lines = [
                f"Koli Modeli: {get_display_name(project.box.box_type)}",
                f"İç Ölçüler: {project.box.length:.1f} × {project.box.width:.1f} × {project.box.height:.1f} mm",
                f"Malzeme: {project.material.name} ({project.material.thickness:.1f} mm)",
                f"Levha Ölçüsü: {project.sheet.width:.1f} × {project.sheet.height:.1f} mm",
            ]
            if self.current_pattern:
                lines.append(
                    f"Açınım Boyutu: {self.current_pattern.width:.1f} × {self.current_pattern.height:.1f} mm")
            if self.current_nesting:
                lines.append(f"Levha Başına Koli: {self.current_nesting.count}")
                lines.append(
                    f"Tahmini Boş Alan (dikdörtgen bazlı yaklaşım): %{self.current_nesting.waste_percent:.2f}"
                )
            if error_count == 0:
                # NOT: Bu, yalnızca yazılımın kendi geometrik/levha kontrollerini
                # geçtiği anlamına gelir (çakışma yok, levha dışına taşma yok vb.).
                # Gerçek lazer/CNC makinesinde, seçtiğiniz malzeme ve ayarlarla
                # üretilebilir olduğunun DOĞRULAMASI DEĞİLDİR - bunu mutlaka bir
                # test kesimiyle kontrol edin.
                lines.append("Durum: ✓ Tasarım Kontrollerinden Geçti (son kontrol: test kesimi yapın)")
            else:
                lines.append(f"Durum: ✕ {error_count} Hata Tespit Edildi")
        else:
            lines = [
                f"Box Model: {get_display_name(project.box.box_type)}",
                f"Internal Dimensions: {project.box.length:.1f} × {project.box.width:.1f} × {project.box.height:.1f} mm",
                f"Material: {project.material.name} ({project.material.thickness:.1f} mm)",
                f"Sheet Size: {project.sheet.width:.1f} × {project.sheet.height:.1f} mm",
            ]
            if self.current_pattern:
                lines.append(
                    f"Flat Pattern Size: {self.current_pattern.width:.1f} × {self.current_pattern.height:.1f} mm")
            if self.current_nesting:
                lines.append(f"Boxes Per Sheet: {self.current_nesting.count}")
                lines.append(
                    f"Estimated Empty Area (rectangular approximation): %{self.current_nesting.waste_percent:.2f}"
                )
            if error_count == 0:
                lines.append("Status: ✓ Passed Design Checks (final step: run a test cut)")
            else:
                lines.append(f"Status: ✕ {error_count} Error(s) Detected")

        self.summary_label.setText("\n".join(lines))

    def _choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Çıktı Klasörü Seç")
        if folder:
            self.output_folder_edit.setText(folder)

    def _on_generate_dxf(self):
        if self.current_pattern is None or self.current_nesting is None:
            QMessageBox.warning(self, "Uyarı", "Önce geçerli bir koli tasarımı hesaplanmalı.\n"
                                                "Lütfen üstteki ölçü/ayarları kontrol edin.")
            return
        if has_errors(self.last_validation_results):
            QMessageBox.warning(self, "Uyarı", "Hatalı tasarım için DXF oluşturulamaz. Kontrolleri inceleyin.")
            return

        base_folder = Path(self.output_folder_edit.text().strip() or Path.home() / "Koli_CNC_Projeleri")
        folder_name = make_output_folder_name(self.project.box.length, self.project.box.width, self.project.box.height,
                                              datetime.datetime.now())
        # Aynı saniye içinde art arda export edilirse bile mevcut bir çıktıyı
        # sessizce ezmemek için benzersiz klasör adı garanti edilir.
        project_folder = ensure_unique_folder(base_folder, folder_name)
        folder_name = project_folder.name
        cnc_folder = project_folder / "CNC"
        cnc_folder.mkdir(parents=True, exist_ok=True)

        dxf_path = cnc_folder / f"{folder_name}.dxf"
        try:
            export_nested_sheet_to_dxf(
                self.current_pattern, self.current_nesting.placements,
                self.project.sheet.width, self.project.sheet.height, str(dxf_path),
                include_sheet_outline=self.sheet_outline_checkbox.isChecked()
            )
            QMessageBox.information(self, "Başarılı", f"DXF oluşturuldu:\n{dxf_path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))

    def _on_generate_svg(self):
        if self.current_pattern is None or self.current_nesting is None:
            QMessageBox.warning(self, "Uyarı", "Önce geçerli bir koli tasarımı hesaplanmalı.\n"
                                                "Lütfen üstteki ölçü/ayarları kontrol edin.")
            return
        if has_errors(self.last_validation_results):
            QMessageBox.warning(self, "Uyarı", "Hatalı tasarım için SVG oluşturulamaz. Kontrolleri inceleyin.")
            return

        base_folder = Path(self.output_folder_edit.text().strip() or Path.home() / "Koli_CNC_Projeleri")
        folder_name = make_output_folder_name(self.project.box.length, self.project.box.width, self.project.box.height,
                                              datetime.datetime.now())
        project_folder = ensure_unique_folder(base_folder, folder_name)
        folder_name = project_folder.name
        cnc_folder = project_folder / "CNC"
        cnc_folder.mkdir(parents=True, exist_ok=True)

        svg_path = cnc_folder / f"{folder_name}.svg"
        try:
            export_nested_sheet_to_svg(
                self.current_pattern, self.current_nesting.placements,
                self.project.sheet.width, self.project.sheet.height, str(svg_path),
                include_sheet_outline=self.sheet_outline_checkbox.isChecked()
            )
            QMessageBox.information(self, "Başarılı", f"SVG oluşturuldu:\n{svg_path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))

    def _new_project(self):
        self.project = Project()
        self.project.design_mode = "direct_box"
        self.project_filepath = None
        self._load_project_into_form()
        self._auto_recalculate()

    def _save_project(self):
        if not self.project_filepath:
            self._save_project_as()
            return
        try:
            save_project(self._collect_project(), self.project_filepath)
        except OSError as exc:
            QMessageBox.critical(self, "Kaydetme Hatası", f"Proje kaydedilemedi:\n\n{exc}")
            return
        self.status_bar.showMessage("Proje kaydedildi.")

    def _save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Farklı Kaydet", "proje.json", "JSON (*.json)")
        if path:
            self.project_filepath = path
            self._save_project()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Proje Aç", "", "JSON (*.json)")
        if path:
            try:
                project = load_project(path)
            except (OSError, ValueError, TypeError) as exc:   # JSONDecodeError de ValueError'dır
                QMessageBox.critical(self, "Proje Açma Hatası", f"Dosya açılamadı:\n\n{exc}")
                return
            self.project = project
            self.project_filepath = path
            self._load_project_into_form()
            self._auto_recalculate()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # platformdan bağımsız tutarlı görünüm (bkz. main.py)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()