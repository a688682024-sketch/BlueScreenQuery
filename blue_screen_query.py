import sys
import json
import os
from difflib import SequenceMatcher
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QDialog, QTextEdit,
    QGraphicsOpacityEffect, QStatusBar, QScrollArea, QGridLayout,
    QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QTimer
from PyQt5.QtGui import QFont, QColor, QCursor, QPalette


class CardButton(QFrame):
    """长方形圆角卡片按钮 - 带悬停渐变动画"""
    def __init__(self, code, name, data, parent=None):
        super().__init__(parent)
        self.code = code
        self.name = name
        self.data = data
        self.main_window = parent
        
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedHeight(82)
        self.setMinimumWidth(170)
        
        # 初始颜色
        self.normal_bg = QColor("#1a1a2e")
        self.hover_bg = QColor("#1e2a4a")
        self.normal_border = QColor(255, 255, 255, 25)
        self.hover_border = QColor("#2196F3")
        self.current_bg = self.normal_bg
        self.current_border = self.normal_border
        
        # 标志位：是否处于悬停状态
        self.is_hovered = False
        
        # 背景色动画
        self.bg_anim = QPropertyAnimation(self, b"bg_color")
        self.bg_anim.setDuration(250)
        self.bg_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.bg_anim.finished.connect(self.on_anim_finished)
        
        # 边框色动画
        self.border_anim = QPropertyAnimation(self, b"border_color")
        self.border_anim.setDuration(250)
        self.border_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        # 透明度动画（整体淡入）- 搜索时不做淡入，直接显示
        self.opacity_effect = QGraphicsOpacityEffect()
        self.opacity_effect.setOpacity(1)
        self.setGraphicsEffect(self.opacity_effect)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        # 代码标签
        self.code_label = QLabel(code)
        self.code_label.setStyleSheet("""
            color: #64B5F6;
            font-size: 14px;
            font-weight: bold;
            font-family: 'Consolas', 'Courier New', monospace;
            border: none;
            background: transparent;
        """)
        layout.addWidget(self.code_label)
        
        # 名称标签
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("""
            color: #E0E0E0;
            font-size: 12px;
            border: none;
            background: transparent;
        """)
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        
        # 提示文字
        hint = QLabel("▶ 点击查看详情")
        hint.setStyleSheet("""
            color: rgba(255,255,255,0.25);
            font-size: 10px;
            border: none;
            background: transparent;
        """)
        layout.addWidget(hint)
        
        # 应用初始样式
        self.update_style()
    
    def get_bg_color(self):
        return self.current_bg
    
    def set_bg_color(self, color):
        self.current_bg = color
        self.update_style()
    
    bg_color = pyqtProperty(QColor, get_bg_color, set_bg_color)
    
    def get_border_color(self):
        return self.current_border
    
    def set_border_color(self, color):
        self.current_border = color
        self.update_style()
    
    border_color = pyqtProperty(QColor, get_border_color, set_border_color)
    
    def update_style(self):
        bg = self.current_bg.name()
        border = self.current_border.name()
        self.setStyleSheet(f"""
            CardButton {{
                background: {bg};
                border: 2px solid {border};
                border-radius: 10px;
            }}
        """)
    
    def on_anim_finished(self):
        """动画完成后更新悬停状态"""
        pass
    
    def enterEvent(self, event):
        if self.is_hovered:
            return
        self.is_hovered = True
        
        self.bg_anim.stop()
        self.border_anim.stop()
        
        self.bg_anim.setStartValue(self.current_bg)
        self.bg_anim.setEndValue(self.hover_bg)
        self.bg_anim.start()
        
        self.border_anim.setStartValue(self.current_border)
        self.border_anim.setEndValue(self.hover_border)
        self.border_anim.start()
        
        # 更新状态栏
        if self.main_window:
            meaning = self.data.get('meaning', '')
            short_meaning = meaning[:30] + '...' if len(meaning) > 30 else meaning
            self.main_window.update_status_info(f"{self.code} | {self.name} | {short_meaning}")
        
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        if not self.is_hovered:
            return
        self.is_hovered = False
        
        self.bg_anim.stop()
        self.border_anim.stop()
        
        self.bg_anim.setStartValue(self.current_bg)
        self.bg_anim.setEndValue(self.normal_bg)
        self.bg_anim.start()
        
        self.border_anim.setStartValue(self.current_border)
        self.border_anim.setEndValue(self.normal_border)
        self.border_anim.start()
        
        # 恢复状态栏
        if self.main_window:
            self.main_window.update_status_info("将鼠标悬停到卡片上查看代码信息")
        
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        """全区域点击"""
        if event.button() == Qt.LeftButton:
            self.main_window.show_detail_from_card(self.data)
        super().mousePressEvent(event)


class DetailDialog(QDialog):
    """详情弹窗 - 带淡入动画"""
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"蓝屏代码 {data['code']} 详解")
        self.setFixedSize(700, 590)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 主容器
        container = QFrame(self)
        container.setGeometry(10, 10, 680, 570)
        container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border: 2px solid #2196F3;
                border-radius: 15px;
            }
        """)
        
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(22, 18, 22, 18)
        
        # 标题行
        title_layout = QHBoxLayout()
        title = QLabel(f"<h1 style='color:#64B5F6;margin:0;'>{data['code']}</h1>")
        title_layout.addWidget(title)
        
        # 关闭按钮
        close_btn = QPushButton("✕")
        close_btn.setObjectName("detail_close_btn")
        close_btn.setFixedSize(34, 34)
        close_btn.setStyleSheet("""
            QPushButton#detail_close_btn {
                background: rgba(255, 255, 255, 0.15);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 17px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton#detail_close_btn:hover {
                background: #f44336 !important;
                border: 1px solid #d32f2f !important;
                color: white !important;
            }
            QPushButton#detail_close_btn:pressed {
                background: #d32f2f !important;
            }
        """)
        close_btn.clicked.connect(self.close)
        title_layout.addWidget(close_btn, alignment=Qt.AlignRight)
        layout.addLayout(title_layout)
        
        # 名称区块
        name_frame = QFrame()
        name_frame.setStyleSheet("""
            QFrame {
                background: rgba(255,152,0,0.1);
                border-radius: 8px;
                padding: 8px;
                border: none;
            }
        """)
        name_layout = QHBoxLayout(name_frame)
        name_layout.setContentsMargins(10, 5, 10, 5)
        name_label = QLabel(f"<b style='color:#FF9800;font-size:15px;'>完整名称：</b><span style='color:#E0E0E0;font-size:14px;'>{data['name']}</span>")
        name_label.setWordWrap(True)
        name_label.setStyleSheet("border: none; background: transparent;")
        name_layout.addWidget(name_label)
        layout.addWidget(name_frame)
        
        # 含义区块
        meaning_frame = QFrame()
        meaning_frame.setStyleSheet("""
            QFrame {
                background: rgba(76,175,80,0.1);
                border-radius: 8px;
                padding: 8px;
                border: none;
            }
        """)
        meaning_layout = QVBoxLayout(meaning_frame)
        meaning_layout.setContentsMargins(10, 5, 10, 5)
        meaning_title = QLabel("<b style='color:#4CAF50;font-size:15px;'>📖 含义解释：</b>")
        meaning_title.setStyleSheet("border: none; background: transparent;")
        meaning_layout.addWidget(meaning_title)
        meaning_content = QLabel(data['meaning'])
        meaning_content.setWordWrap(True)
        meaning_content.setStyleSheet("""
            color: #E0E0E0;
            font-size: 13px;
            line-height: 1.6;
            border: none;
            background: transparent;
        """)
        meaning_layout.addWidget(meaning_content)
        layout.addWidget(meaning_frame)
        
        # 解决方法区块
        solution_frame = QFrame()
        solution_frame.setStyleSheet("""
            QFrame {
                background: rgba(244,67,54,0.08);
                border-radius: 8px;
                padding: 8px;
                border: none;
            }
        """)
        solution_layout = QVBoxLayout(solution_frame)
        solution_layout.setContentsMargins(10, 5, 10, 5)
        solution_title = QLabel("<b style='color:#f44336;font-size:15px;'>🔧 解决方法：</b>")
        solution_title.setStyleSheet("border: none; background: transparent;")
        solution_layout.addWidget(solution_title)
        
        solution_text = QTextEdit()
        solution_text.setHtml(f"<pre style='color:#E0E0E0;font-size:13px;font-family:Microsoft YaHei, sans-serif;line-height:1.8;white-space:pre-wrap;'>{data['solution']}</pre>")
        solution_text.setReadOnly(True)
        solution_text.setStyleSheet("""
            QTextEdit {
                background: rgba(0,0,0,0.2);
                border: none;
                border-radius: 8px;
                padding: 10px;
                color: #E0E0E0;
            }
        """)
        solution_layout.addWidget(solution_text)
        layout.addWidget(solution_frame)
        
        # 弹窗淡入动画
        self.opacity_effect = QGraphicsOpacityEffect()
        container.setGraphicsEffect(self.opacity_effect)
        self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in.setDuration(280)
        self.fade_in.setStartValue(0)
        self.fade_in.setEndValue(1)
        self.fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_in.start()


class BlueScreenQuery(QMainWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.data = self.load_data()
        self.filtered_data = self.data[:]
        self.card_widgets = []
        self.init_ui()
    
    def load_data(self):
        """加载蓝屏代码数据"""
        try:
            if hasattr(sys, '_MEIPASS'):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            data_path = os.path.join(base_path, "bluescreen_data.json")
            with open(data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"加载数据失败: {e}")
            return []
    
    def init_ui(self):
        self.setWindowTitle("蓝屏代码查询器 v2.0")
        self.setGeometry(100, 100, 1080, 820)
        self.setMinimumSize(940, 730)
        
        # 全局样式
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f0c29, stop:0.5 #302b63, stop:1 #24243e);
                border: 2px solid #2196F3;
                border-radius: 10px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: rgba(255,255,255,0.03);
                width: 8px;
                border-radius: 4px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.15);
                border-radius: 4px;
                min-height: 30px;
                border: none;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255,255,255,0.25);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QLineEdit {
                background: rgba(255,255,255,0.08);
                border: 2px solid rgba(255,255,255,0.15);
                border-radius: 12px;
                padding: 14px 22px;
                color: white;
                font-size: 16px;
            }
            QLineEdit:focus {
                border-color: #2196F3;
                background: rgba(255,255,255,0.12);
            }
            QStatusBar {
                background: rgba(0,0,0,0.3);
                color: #aaa;
                border-top: 1px solid rgba(255,255,255,0.05);
                padding: 5px;
                border: none;
            }
            QWidget {
                border: none;
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(18, 12, 18, 8)
        
        # 标题
        title = QLabel("<h1 style='color:#64B5F6;font-weight:300;letter-spacing:2px;'>🔵 蓝屏代码查询器</h1>")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("border: none; background: transparent;")
        main_layout.addWidget(title)
        
        # 副标题
        subtitle = QLabel("<span style='color:rgba(255,255,255,0.4);font-size:13px;'>点击卡片查看详细解决方案 · 支持模糊搜索 · 悬停查看简介</span>")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("border: none; background: transparent;")
        main_layout.addWidget(subtitle)
        
        # 搜索区域
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入蓝屏代码或关键词搜索...")
        self.search_input.textChanged.connect(self.on_search)
        search_layout.addWidget(self.search_input)
        
        self.clear_btn = QPushButton("✕ 清空")
        self.clear_btn.setFixedWidth(88)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.1);
                color: white;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 10px;
                padding: 12px;
                font-size: 14px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.2);
                border-color: #2196F3;
            }
            QPushButton:pressed {
                background: rgba(255,255,255,0.05);
            }
        """)
        self.clear_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(self.clear_btn)
        main_layout.addLayout(search_layout)
        
        # 统计信息
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px; padding-left: 5px; border: none; background: transparent;")
        main_layout.addWidget(self.count_label)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent; border: none;")
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # 底部信息栏
        bottom_widget = QWidget()
        bottom_widget.setFixedHeight(42)
        bottom_widget.setStyleSheet("""
            background: rgba(0, 0, 0, 0.2);
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 0px;
            border: none;
        """)
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(15, 5, 15, 5)
        
        # 左下角状态信息
        self.status_info = QLabel("将鼠标悬停到卡片上查看代码信息")
        self.status_info.setStyleSheet("""
            color: rgba(255, 255, 255, 0.5);
            font-size: 12px;
            font-family: 'Consolas', 'Microsoft YaHei', monospace;
            border: none;
            background: transparent;
        """)
        bottom_layout.addWidget(self.status_info)
        
        bottom_layout.addStretch()
        
        # 右下角免责声明
        disclaimer = QLabel("仅供参考，使用不当后果自负")
        disclaimer.setStyleSheet("""
            color: rgba(255, 255, 255, 0.3);
            font-size: 11px;
            border: none;
            background: transparent;
        """)
        bottom_layout.addWidget(disclaimer)
        
        main_layout.addWidget(bottom_widget)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # 填充卡片
        self.populate_cards(self.data)
    
    def create_card(self, item):
        """创建一个卡片"""
        card = CardButton(item['code'], item['name'], item, self)
        return card
    
    def populate_cards(self, items):
        """填充卡片网格 - 每行5个，卡片一次性全部显示"""
        # 清除旧卡片
        for card in self.card_widgets:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.card_widgets.clear()
        
        cols = 5
        for i, item in enumerate(items):
            card = self.create_card(item)
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(card, row, col)
            self.card_widgets.append(card)
        
        self.update_count(len(items))
    
    def show_detail_from_card(self, data):
        """从卡片显示详情"""
        self.update_status_info(f"当前查看：{data['code']} - {data['name']}")
        dialog = DetailDialog(data, self)
        dialog.exec_()
        self.update_status_info("将鼠标悬停到卡片上查看代码信息")
    
    def update_status_info(self, text):
        """更新左下角状态信息"""
        self.status_info.setText(text)
    
    def on_search(self):
        """搜索过滤"""
        keyword = self.search_input.text().strip()
        if not keyword:
            self.filtered_data = self.data[:]
        else:
            self.filtered_data = []
            for item in self.data:
                score_code = SequenceMatcher(None, keyword.lower(), item['code'].lower()).ratio()
                score_name = SequenceMatcher(None, keyword.lower(), item['name'].lower()).ratio()
                score_meaning = SequenceMatcher(None, keyword.lower(), item['meaning'].lower()).ratio()
                
                max_score = max(score_code, score_name, score_meaning)
                
                if (keyword.lower() in item['code'].lower() or 
                    keyword.lower() in item['name'].lower() or 
                    keyword.lower() in item['meaning'].lower()):
                    max_score = max(max_score, 0.6)
                
                if max_score >= 0.25:
                    self.filtered_data.append(item)
        
        self.filtered_data.sort(
            key=lambda x: SequenceMatcher(None, keyword.lower(), x['code'].lower()).ratio(),
            reverse=True
        )
        
        self.populate_cards(self.filtered_data)
    
    def clear_search(self):
        """清空搜索"""
        self.search_input.clear()
        self.filtered_data = self.data[:]
        self.populate_cards(self.data)
    
    def update_count(self, count):
        """更新计数"""
        self.count_label.setText(f"共 {count} 条蓝屏代码")
        self.status_bar.showMessage(f"共找到 {count} 条蓝屏代码")


def main():
    app = QApplication(sys.argv)
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    window = BlueScreenQuery()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()