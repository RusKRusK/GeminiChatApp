import os
import json
import mimetypes
import sys
import re
from dotenv import load_dotenv
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWebEngineWidgets import *
from PyQt5.QtWebChannel import *
import google.generativeai as genai
import markdown

# APIキー設定
load_dotenv()
api_key = os.getenv("GENAI_API_KEY")
if not api_key:
    raise ValueError("環境変数 GENAI_API_KEY が見つかりません。")
genai.configure(api_key=api_key)

# モデル初期化
def init_model(system_instruction="", history_param=None):
    model = genai.GenerativeModel(
        model_name='gemini-2.0-flash', 
        system_instruction=system_instruction.strip() if system_instruction.strip() else None
    )
    return model.start_chat(history=history_param or [])

class LinkHandler(QObject):
    @pyqtSlot(str)
    def link_click(self, url):
        reply = QMessageBox.question(
            None, "確認", f"このリンクを開きますか？\n\n{url}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(url))

class ChatProcess(QThread):
    message_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, convo, message, media_data=None):
        super().__init__()
        self.convo = convo
        self.message = message
        self.media_data = media_data
    
    def run(self):
        try:
            if self.media_data:
                self.convo.send_message([self.media_data, self.message])
            else:
                self.convo.send_message(self.message)
            reply = self.convo.last.text
            self.message_received.emit(reply)
        except Exception as e:
            self.error_occurred.emit(f"{type(e).__name__} - {e}")


class GeminiChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.system_instruction = ""
        self.convo = init_model(self.system_instruction)
        self.history = []
        self.model_name = "モデル"
        self.chat_markdown = ""
        self.current_worker = None
        self.is_processing = False
        self.is_dark_theme = False
        
        self.init_ui()
        self.setup_theme_palettes()
        self.channel = QWebChannel()
        self.link_handler = LinkHandler()
        self.channel.registerObject("linkHandler", self.link_handler)
        self.chat_html_view.page().setWebChannel(self.channel)
        self.add_message("[システム]", "Geminiチャットへようこそ。")
    
    def setup_theme_palettes(self):
        app = QApplication.instance()

        app.setStyle("Fusion")
        
        # ダークテーマのパレット
        self.dark_palette = app.palette()
        self.dark_palette.setColor(self.dark_palette.Window, QColor(53, 53, 53))
        self.dark_palette.setColor(self.dark_palette.WindowText, QColor(255, 255, 255))
        self.dark_palette.setColor(self.dark_palette.Base, QColor(25, 25, 25))
        self.dark_palette.setColor(self.dark_palette.AlternateBase, QColor(53, 53, 53))
        self.dark_palette.setColor(self.dark_palette.ToolTipBase, QColor(255, 255, 255))
        self.dark_palette.setColor(self.dark_palette.ToolTipText, QColor(255, 255, 255))
        self.dark_palette.setColor(self.dark_palette.Text, QColor(255, 255, 255))
        self.dark_palette.setColor(self.dark_palette.Button, QColor(53, 53, 53))
        self.dark_palette.setColor(self.dark_palette.ButtonText, QColor(255, 255, 255))
        self.dark_palette.setColor(self.dark_palette.BrightText, QColor(255, 0, 0))
        self.dark_palette.setColor(self.dark_palette.Highlight, QColor(142, 45, 197))
        self.dark_palette.setColor(self.dark_palette.HighlightedText, QColor(255, 255, 255))
        
        self.light_palette = app.style().standardPalette()
        
    def init_ui(self):
        self.setWindowTitle("Gemini チャット")
        self.setGeometry(100, 100, 1000, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # システムインタラクション・チャット欄・入力欄の3分割
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # システムインタラクション
        sys_frame = QFrame()
        sys_layout = QHBoxLayout(sys_frame)
        sys_layout.setContentsMargins(0, 0, 0, 0)
        sys_layout.setSpacing(10)

        sys_label = QLabel("システムインタラクション:")
        sys_label.setMinimumWidth(150)
        sys_label.setMaximumWidth(150)
        sys_layout.addWidget(sys_label)

        self.sys_inst_entry = QTextEdit()
        self.sys_inst_entry.setPlaceholderText("システムインタラクションを入力してください...")
        self.sys_inst_entry.setAcceptRichText(False)
        sys_layout.addWidget(self.sys_inst_entry)

        self.apply_btn = QPushButton("適用")
        self.apply_btn.clicked.connect(self.apply_system_instruction)
        self.apply_btn.setMaximumWidth(60)
        self.apply_btn.setMinimumWidth(60)
        sys_layout.addWidget(self.apply_btn)

        splitter.addWidget(sys_frame)

        # チャット欄
        self.chat_tabs = QTabWidget()
        
        # HTML
        self.chat_html_view = QWebEngineView()
        self.chat_html_view.setAcceptDrops(True)
        self.chat_html_view.dragEnterEvent = self.drag_enter_event
        self.chat_html_view.dropEvent = self.drop_event
        self.chat_tabs.addTab(self.chat_html_view, "HTML表示")
        
        # テキスト
        self.chat_text_view = QTextEdit()
        self.chat_text_view.setReadOnly(True)
        self.chat_text_view.setAcceptDrops(True)
        self.chat_text_view.dragEnterEvent = self.drag_enter_event
        self.chat_text_view.dropEvent = self.drop_event
        font = QFont("Courier New", 10)
        font.setFixedPitch(True)
        self.chat_text_view.setFont(font)
        self.chat_tabs.addTab(self.chat_text_view, "テキスト表示")
        
        self.chat_tabs.currentChanged.connect(self.on_tab_changed)
        
        splitter.addWidget(self.chat_tabs)

        # 入力欄
        input_frame = QFrame()
        input_layout = QVBoxLayout(input_frame)

        # 入力と送信
        input_row = QHBoxLayout()
        self.user_input = QTextEdit()
        self.user_input.setPlaceholderText("メッセージを入力してください... (Ctrl+Enter で送信)")
        self.user_input.setAcceptRichText(False)
        self.user_input.keyPressEvent = self.key_press
        input_row.addWidget(self.user_input)

        self.send_btn = QPushButton("送信\n(Ctrl+Enter)")
        self.send_btn.clicked.connect(self.send_text)
        self.send_btn.setMaximumWidth(100)
        input_row.addWidget(self.send_btn)

        input_layout.addLayout(input_row)

        # 画面下部のボタンたち
        btn_layout = QHBoxLayout()
        
        btn_layout.addStretch()

        self.media_btn = QPushButton("メディア送信")
        self.media_btn.clicked.connect(self.send_media)
        self.media_btn.setMaximumWidth(100)
        btn_layout.addWidget(self.media_btn)

        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self.save_chat)
        self.save_btn.setMaximumWidth(60)
        btn_layout.addWidget(self.save_btn)

        self.load_btn = QPushButton("読み込み")
        self.load_btn.clicked.connect(self.load_chat)
        self.load_btn.setMaximumWidth(80)
        btn_layout.addWidget(self.load_btn)

        self.reset_btn = QPushButton("リセット")
        self.reset_btn.clicked.connect(self.reset_chat)
        self.reset_btn.setMaximumWidth(70)
        btn_layout.addWidget(self.reset_btn)

        btn_layout.addStretch()

        self.dark_theme_checkbox = QCheckBox("ダークテーマ")
        self.dark_theme_checkbox.setChecked(self.is_dark_theme)
        self.dark_theme_checkbox.stateChanged.connect(self.toggle_theme)
        btn_layout.addWidget(self.dark_theme_checkbox)

        input_layout.addLayout(btn_layout)

        splitter.addWidget(input_frame)

        splitter.setSizes([80, 520, 200])
        splitter.setStretchFactor(0, 1)  # sys_frame
        splitter.setStretchFactor(1, 5)  # chat_tabs
        splitter.setStretchFactor(2, 2)  # input_frame

        QTimer.singleShot(100, self.update_chat)

    def toggle_theme(self, state):
        self.is_dark_theme = state == 2
        app = QApplication.instance()
        
        if self.is_dark_theme:
            app.setPalette(self.dark_palette)
        else:
            app.setPalette(self.light_palette)
        
        self.update_chat()

    def get_html_theme_styles(self):
        base_light = """
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                margin: 15px; 
                line-height: 1.6; 
                background-color: #f8f9fa;
                color: #000000;
            }
            h1, h2, h3, h4, h5, h6 { color: #333; margin-top: 20px; margin-bottom: 10px; }
            .user { color: #0066cc; font-weight: bold; }
            .model { color: #009900; font-weight: bold; }
            .system { color: #666666; font-style: italic; }
            .error { color: #cc0000; font-weight: bold; }
            pre { background-color: #f1f3f4; padding: 15px; border-radius: 8px; overflow-x: auto;
                border-left: 4px solid #4285f4; font-family: 'Courier New', monospace; white-space: pre-wrap; }
            code { background-color: #e8eaed; padding: 2px 6px; border-radius: 4px; font-family: 'Courier New', monospace; }
            blockquote { border-left: 4px solid #ddd; margin-left: 0; padding: 10px 20px;
                        background-color: #f9f9f9; border-radius: 4px; }
            table { border-collapse: collapse; width: 100%; margin: 10px 0; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; font-weight: bold; }
            ul, ol { margin: 10px 0; padding-left: 20px; }
            li { margin: 5px 0; }
            p { margin: 10px 0; }
            hr { border: none; border-top: 1px solid #ddd; margin: 20px 0; }
            strong { font-weight: bold; }
            em { font-style: italic; }
        """

        base_dark = """
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                margin: 15px; 
                line-height: 1.6; 
                background-color: #2b2b2b;
                color: #ffffff;
            }
            h1, h2, h3, h4, h5, h6 { color: #ffffff; margin-top: 20px; margin-bottom: 10px; }
            .user { color: #66b3ff; font-weight: bold; }
            .model { color: #66ff66; font-weight: bold; }
            .system { color: #cccccc; font-style: italic; }
            .error { color: #ff6666; font-weight: bold; }
            pre { background-color: #1e1e1e; padding: 15px; border-radius: 8px; overflow-x: auto;
                border-left: 4px solid #4285f4; font-family: 'Courier New', monospace; white-space: pre-wrap;
                color: #ffffff; }
            code { background-color: #3c3c3c; padding: 2px 6px; border-radius: 4px; 
                font-family: 'Courier New', monospace; color: #ffffff; }
            blockquote { border-left: 4px solid #555; margin-left: 0; padding: 10px 20px;
                        background-color: #363636; border-radius: 4px; }
            table { border-collapse: collapse; width: 100%; margin: 10px 0; }
            th, td { border: 1px solid #555; padding: 8px; text-align: left; }
            th { background-color: #404040; font-weight: bold; }
            ul, ol { margin: 10px 0; padding-left: 20px; }
            li { margin: 5px 0; }
            p { margin: 10px 0; }
            hr { border: none; border-top: 1px solid #555; margin: 20px 0; }
            strong { font-weight: bold; }
            em { font-style: italic; }
            a { color: #66b3ff; }
            a:visited { color: #b366ff; }
        """

        return base_dark if self.is_dark_theme else base_light

    def on_tab_changed(self, index):
        if index == 0:
            self.update_chat()
        elif index == 1:
            self.update_text()
    
    def set_input_enabled(self, enabled):
        widgets = [self.user_input, self.send_btn, self.media_btn, self.apply_btn, self.sys_inst_entry]
        for widget in widgets:
            widget.setEnabled(enabled)
        
        if enabled:
            self.send_btn.setText("送信\n(Ctrl+Enter)")
            self.user_input.setPlaceholderText("メッセージを入力してください... (Ctrl+Enter で送信)")
        else:
            self.send_btn.setText("処理中...")
            self.user_input.setPlaceholderText("処理中...")
    
    def drag_enter_event(self, event):
        if not self.is_processing and event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def drop_event(self, event):
        if self.is_processing:
            return
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.drop_file(file_path)
    
    def key_press(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if event.modifiers() == Qt.ControlModifier and not self.is_processing: # Ctrl+Enter
                self.send_text()
                return
        QTextEdit.keyPressEvent(self.user_input, event)
    
    def apply_system_instruction(self):
        if not self.is_processing:
            instruction = self.sys_inst_entry.toPlainText().strip()
            self.system_instruction = instruction
            self.convo = init_model(self.system_instruction)
            self.history.clear()
            self.chat_markdown = ""
            self.chat_text_content = ""
            self.add_message("[システム]", "システムインタラクションを更新し、会話をリセットしました。")
    
    def update_chat(self):        
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                {}
            </style>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/{}.min.css">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
                onload="renderMathInElement(document.body, {{
                    delimiters: [
                        {{left: '$$', right: '$$', display: true}},
                        {{left: '$', right: '$', display: false}}
                    ],
                    throwOnError: false
                }});">
            </script>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
            <script>hljs.highlightAll();</script>
            <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    new QWebChannel(qt.webChannelTransport, function(channel) {{
                        window.linkHandler = channel.objects.linkHandler;
                        document.querySelectorAll("a").forEach(function(link) {{
                            const href = link.getAttribute("href");
                            if (href && href.startsWith("http")) {{
                                link.onclick = function(e) {{
                                    e.preventDefault();
                                    linkHandler.link_click(href);
                                }};
                            }}
                        }});
                    }});
                }});
            </script>
        </head>
        <body>
            {}
            <script>
                setTimeout(function() {{
                    window.scrollTo(0, document.body.scrollHeight);
                }}, 100);
            </script>
        </body>
        </html>
        """

        if self.chat_markdown:
            def extract_math_expressions(text):
                math_blocks = []
                def replacer(match):
                    math_blocks.append(match.group(0))
                    return f"@@MATH{len(math_blocks)-1}@@"
                text = re.sub(r"\$\$(.+?)\$\$", replacer, text, flags=re.DOTALL)
                text = re.sub(r"(?<!\$)\$(.+?)\$(?!\$)", replacer, text, flags=re.DOTALL)

                return text, math_blocks

            def restore_math_expressions(text, math_blocks):
                for i, expr in enumerate(math_blocks):
                    text = text.replace(f"@@MATH{i}@@", expr)
                return text

            protected_text, math_exprs = extract_math_expressions(self.chat_markdown)
            html_content = markdown.markdown(
                protected_text,
                extensions=[
                    'fenced_code',
                    'tables', 'nl2br', 'toc', 'attr_list', 'def_list'
                ]
            )
            html_content = restore_math_expressions(html_content, math_exprs)
        else:
            html_content = "<p>チャットを開始してください</p>"

        theme_styles = self.get_html_theme_styles()
        highlight_theme = "atom-one-dark" if self.is_dark_theme else "atom-one-light"
        
        final_html = html_template.format(theme_styles, highlight_theme, html_content)
        self.chat_html_view.setHtml(final_html)
    
    def update_text(self):
        if not hasattr(self, 'chat_text_content'):
            self.chat_text_content = ""
        
        self.chat_text_view.setPlainText(self.chat_text_content)
        cursor = self.chat_text_view.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_text_view.setTextCursor(cursor)
    
    def regenerate(self):
        self.chat_text_content = ""
        
        self.chat_text_content += "[システム] Geminiチャットへようこそ。\n" + "-"*30 + "\n\n"
        
        for entry in self.history:
            role = entry.get('role', '')
            parts = entry.get('parts', '')
            
            if role == 'user':
                if isinstance(parts, list):
                    # メディア付きメッセージの場合(そもそもメディア自体を保存していないので、この処理は不要かも（そのためメディアを添付した会話は再開不可能）)
                    text_parts = [p for p in parts if isinstance(p, str)]
                    media_parts = [p for p in parts if isinstance(p, dict)]
                    
                    if media_parts:
                        file_info = f"**ファイル**: {media_parts[0].get('data', 'メディアファイル')}"
                        if text_parts:
                            file_info += f"\n\n**メッセージ**: {text_parts[0]}"
                        self.chat_text_content += f"[あなた]\n{file_info}\n" + "="*50 + "\n\n"
                    else:
                        self.chat_text_content += f"[あなた]\n{parts[0] if parts else ''}\n" + "="*50 + "\n\n"
                else:
                    self.chat_text_content += f"[あなた]\n{parts}\n" + "="*50 + "\n\n"
            elif role == 'model':
                self.chat_text_content += f"[モデル]\n{parts}\n" + "="*50 + "\n\n"

    def escape_except_code_blocks(self, text):
        # HTMLのエスケープ時に、コードブロック内の文字が二重にエスケープされるので、その部分だけエスケープしないように設定。具体的には内容を一時的に保持しておいて、エスケープ後に復元する。
        # なお、言語名部分に<script>タグを入れると実行されてしまったので、一行目にタグがあれば削除する。
            code_blocks = []
            inline_codes = []

            def is_htmltag(line):
                return bool(re.match(r'^```<[^>]+>', line.strip()))

            result_lines = []
            in_code_block = False
            current_code_block = []
            code_block_lang = ""

            lines = text.splitlines()

            for line in lines:
                if not in_code_block:
                    if line.strip().startswith("```"):
                        in_code_block = True
                        code_block_lang = line.strip()
                        if is_htmltag(code_block_lang):
                            current_code_block = ["```"]
                        else:
                            current_code_block = [code_block_lang]
                    else:
                        def inline_replacer(m):
                            inline_codes.append(m.group(0))
                            return f"@@INLINE{len(inline_codes)-1}@@"

                        safe_line = re.sub(r"`[^`\n]+?`", inline_replacer, line)
                        safe_line = safe_line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        result_lines.append(safe_line)
                else:
                    current_code_block.append(line)
                    if line.strip() == "```":
                        in_code_block = False
                        placeholder = f"@@CODEBLOCK{len(code_blocks)}@@"
                        code_blocks.append("\n".join(current_code_block))
                        result_lines.append(placeholder)

            final_text = "\n".join(result_lines)
            for i, code in enumerate(code_blocks):
                final_text = final_text.replace(f"@@CODEBLOCK{i}@@", code)
            for i, inline in enumerate(inline_codes):
                final_text = final_text.replace(f"@@INLINE{i}@@", inline)

            return final_text

    def add_message(self, sender, text):
        self.escaped_text = self.escape_except_code_blocks(text)
        if sender == "[あなた]":
            self.chat_markdown += f"#### <span class='user'>あなた</span>\n\n{self.escaped_text}\n\n---\n\n"
        elif sender == "[モデル]":
            self.chat_markdown += f"#### <span class='model'>モデル</span>\n\n{self.escaped_text}\n\n---\n\n"
        elif sender == "[システム]":
            self.chat_markdown += f"#### <span class='system'>システム</span>\n\n*{self.escaped_text}*\n\n---\n\n"
        elif sender == "[エラー]":
            self.chat_markdown += f"#### <span class='error'>エラー</span>\n\n**{self.escaped_text}**\n\n---\n\n"
        else:
            self.chat_markdown += f"#### {sender}\n\n{self.escaped_text}\n\n---\n\n"
        
        if not hasattr(self, 'chat_text_content'):
            self.chat_text_content = ""
        
        if sender == "[あなた]":
            self.chat_text_content += f"[あなた]\n{text}\n" + "="*50 + "\n\n"
        elif sender == "[モデル]":
            self.chat_text_content += f"[モデル]\n{text}\n" + "="*50 + "\n\n"
        elif sender == "[システム]":
            self.chat_text_content += f"[システム] {text}\n" + "-"*30 + "\n\n"
        elif sender == "[エラー]":
            self.chat_text_content += f"[エラー] {text}\n" + "-"*30 + "\n\n"
        else:
            self.chat_text_content += f"{sender}\n{text}\n" + "="*50 + "\n\n"
        
        self.update_chat()
        self.update_text()
    
    def send_text(self):
        if self.is_processing:
            return
        
        message = self.user_input.toPlainText().strip()
        if not message:
            return
        
        self.is_processing = True
        self.set_input_enabled(False)
        
        self.user_input.clear()
        self.add_message("[あなた]", message)
        
        # 非同期処理のためスレッドをわける
        self.current_worker = ChatProcess(self.convo, message)
        self.current_worker.message_received.connect(self.message_received)
        self.current_worker.error_occurred.connect(self.add_error)
        self.current_worker.finished.connect(self.processing_finish)
        self.current_worker.start()
    
    def message_received(self, reply):
        self.add_message("[モデル]", reply)
        self.history.extend([
            {'role': 'user', 'parts': self.current_worker.message}, 
            {'role': 'model', 'parts': reply}
        ])
    
    def add_error(self, error_msg):
        self.add_message("[エラー]", error_msg)
    
    def processing_finish(self):
        self.is_processing = False
        self.set_input_enabled(True)
        self.user_input.setFocus()
    
    def drop_file(self, file_path):

        def is_text_file(file_path, try_bytes=512):
            try:
                with open(file_path, 'rb') as f:
                    chunk = f.read(try_bytes)
                if b'\x00' in chunk:
                    return False
                try:
                    chunk.decode('utf-8')
                    return True
                except UnicodeDecodeError:
                    return False
            except Exception:
                return False

        if self.is_processing:
            return
        
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            if is_text_file(file_path):
                mime_type = "text/plain"
            else:
                self.add_message("[システム]", "対応していないメディア形式です。")
                return
        elif not (mime_type.startswith(("image/", "video/", "audio/", "text/")) or mime_type == "application/pdf"):
            if is_text_file(file_path):
                mime_type = "text/plain"
            else:
                self.add_message("[システム]", "対応していないメディア形式です。")
                return

        self.is_processing = True
        self.set_input_enabled(False)

        user_message = self.user_input.toPlainText().strip()
        self.user_input.clear()
        
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            
            file_info = f"**ファイル**: `{os.path.basename(file_path)}` ({mime_type})"
            if user_message:
                file_info += f"\n\n**メッセージ**: {user_message}"
            
            self.add_message("[あなた]", file_info)
            
            media_data = {"mime_type": mime_type, "data": file_bytes}
            
            self.current_worker = ChatProcess(self.convo, user_message or "", media_data)
            self.current_worker.message_received.connect(
                lambda reply: self.media_received(reply, file_path, user_message, mime_type)
            )
            self.current_worker.error_occurred.connect(self.add_error)
            self.current_worker.finished.connect(self.processing_finish)
            self.current_worker.start()
            
        except Exception as e:
            self.add_message("[エラー]", f"{type(e).__name__} - {e}")
            self.processing_finish()
    
    def media_received(self, reply, file_path, user_message, mime_type):
        self.add_message("[モデル]", reply)
        
        parts = [{"mime_type": mime_type, "data": f"{file_path}"}]
        if user_message:
            parts.append(user_message)
        
        self.history.append({'role': 'user', 'parts': parts})
        self.history.append({'role': 'model', 'parts': reply})
    
    def send_media(self):
        if self.is_processing:
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "ファイルを選択",
            "",
            "すべてのファイル (*.*)"
        )
        if file_path:
            self.drop_file(file_path)
    
    def save_chat(self):
        if self.is_processing:
            return
        
        if not self.history:
            QMessageBox.information(self, "保存", "保存する会話履歴がありません。")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "会話を保存", "", "JSONファイル (*.json)"
        )
        if not file_path:
            return
        
        try:
            data = {
                "modelName": self.model_name,
                "system_instruction": self.system_instruction,
                "history": self.history,
                "chat_markdown": self.chat_markdown
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            
            self.add_message("[システム]", f"会話履歴を保存しました: `{file_path}`")
        except Exception as e:
            self.add_message("[エラー]", f"保存に失敗しました: {e}")
    
    def load_chat(self):
        if self.is_processing:
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "会話を読み込み", "", "JSONファイル (*.json)"
        )
        if not file_path:
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.system_instruction = data.get("system_instruction", "")
            self.history = data.get("history", [])
            self.chat_markdown = data.get("chat_markdown", "")
            
            self.regenerate()
            
            self.sys_inst_entry.setPlainText(self.system_instruction)
            self.convo = init_model(self.system_instruction, self.history)
            
            self.update_chat()
            self.update_text()
            
            self.add_message("[システム]", f"会話履歴を読み込みました: `{file_path}`")
        except Exception as e:
            self.add_message("[エラー]", f"読み込みに失敗しました: {e}")
    
    def reset_chat(self):
        if self.is_processing:
            return
        
        reply = QMessageBox.question(
            self, "会話リセット", "会話をリセットしますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.convo = init_model(self.system_instruction)
            self.history.clear()
            self.chat_markdown = ""
            self.chat_text_content = ""
            self.add_message("[システム]", "会話をリセットしました。")


def main():
    app = QApplication(sys.argv)
    
    app.setApplicationName("Gemini Chat")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Gemini Chat App")
    
    window = GeminiChatApp()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()