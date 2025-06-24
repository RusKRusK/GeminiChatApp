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
import argparse
import bleach

# APIキー設定
load_dotenv()
api_key = os.getenv("GENAI_API_KEY")
if not api_key:
    raise ValueError("環境変数 GENAI_API_KEY が見つかりません。")
genai.configure(api_key=api_key)

# オプションの取得
parser = argparse.ArgumentParser()
parser.add_argument("--prompt", type=str, help="デフォルトのシステムインストラクション")
parser.add_argument("-d", action="store_true", help="起動時にダークテーマを有効にする")
args = parser.parse_args()
instruction = ""
if args.prompt: # デフォルトのシステムインストラクションを設定する
    instruction = args.prompt

# モデル初期化
def init_model(system_instruction="", history_param=None):
    model = genai.GenerativeModel(
        model_name='gemini-2.0-flash', 
        system_instruction=system_instruction.strip() if system_instruction.strip() else None
    )
    return model.start_chat(history=history_param or [])

# テキストボックスのカーソルについて、一番上/一番下にカーソルがあるときに↑↓キーを押すとカーソルが一番手前/一番末尾に移動するようにクラスを作ってオーバーライド
class CustomTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

    def keyPressEvent(self, event):
        cursor = self.textCursor()
        key = event.key()

        # ↑キー
        if key == Qt.Key_Up:
            # カーソルをあたらしく用意して、上に移動できるか試す
            test_cursor = QTextCursor(cursor)
            test_cursor.movePosition(QTextCursor.Up)
            # テストカーソルの位置が元のカーソル位置と同じとき
            if test_cursor.position() == cursor.position():
                # カーソルをテキストの先頭に移動
                self.moveCursor(QTextCursor.Start)
                event.accept()
                return

        # ↓キー
        elif key == Qt.Key_Down:
            # カーソルをあたらしく用意して、下に移動できるか試す
            test_cursor = QTextCursor(cursor)
            test_cursor.movePosition(QTextCursor.Down)
            # テストカーソルの位置が元のカーソル位置と同じとき
            if test_cursor.position() == cursor.position():
                # カーソルをテキストの末尾に移動
                self.moveCursor(QTextCursor.End)
                event.accept()
                return

        # それ以外
        super().keyPressEvent(event)

# QWebEngineView内で、リンクを開くかどうか確認する
class LinkHandler(QObject):
    @pyqtSlot(str) # JavaScriptからの呼び出しを可能にするデコレータ
    def link_click(self, url):
        reply = QMessageBox.question(
            None, "確認", f"このリンクを開きますか？\n\n{url}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # デフォルトのブラウザで開く
            QDesktopServices.openUrl(QUrl(url))

# 非同期処理用のクラス
class ChatProcess(QThread):
    # シグナルの定義
    message_received = pyqtSignal(str) # メッセージ受信成功時
    error_occurred = pyqtSignal(str) # エラー発生時
    
    def __init__(self, convo, message, media_data=None):
        super().__init__()
        self.convo = convo
        self.message = message
        self.media_data = media_data
    
    def run(self):
        try:
            if self.media_data: # メディアデータがあるか
                self.convo.send_message([self.media_data, self.message])
            else:
                self.convo.send_message(self.message)
            # 返信を取得
            reply = self.convo.last.text
            # シグナルを発行
            self.message_received.emit(reply)
        except Exception as e:
            # 失敗したらしたでエラーのシグナルを発行
            self.error_occurred.emit(f"{type(e).__name__} - {e}")

# 本体
class GeminiChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.system_instruction = instruction # システムインストラクション
        self.convo = init_model(self.system_instruction) # チャット
        self.history = [] # 会話履歴
        self.model_name = "モデル" # モデル名
        self.chat_markdown = "" # マークダウンのチャットログ
        self.current_worker = None # 非同期処理中のスレッド
        self.is_processing = False # APIの返答待ちかどうかのフラグ
        self.is_dark_theme = args.d # オプションによってテーマを変更する
        
        self.init_ui() # UIの初期化
        self.setup_theme_palettes() # ダークテーマのパレットの設定
        # WebChannelとリンククリックをセットアップ
        self.channel = QWebChannel()
        self.link_handler = LinkHandler()
        self.channel.registerObject("linkHandler", self.link_handler)
        self.chat_html_view.page().setWebChannel(self.channel)
        # オプションによってテーマを変更する
        app = QApplication.instance()
        if args.d:
            app.setPalette(self.dark_palette)
        # 初期メッセージを表示
        self.add_message("[システム]", "Geminiチャットへようこそ。")
        self.user_input.setFocus() # メッセージ入力欄にフォーカスする
    
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
        
        # ライトテーマのパレット
        self.light_palette = app.style().standardPalette()
        
    def init_ui(self):
        self.setWindowTitle("Gemini チャット")
        self.setGeometry(100, 100, 1000, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # システムインストラクション・チャット欄・入力欄の3分割
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        # システムインストラクション
        sys_frame = QFrame()
        sys_layout = QHBoxLayout(sys_frame)
        sys_layout.setContentsMargins(0, 0, 0, 0)
        sys_layout.setSpacing(10)

        sys_label = QLabel("システムインストラクション:")
        sys_layout.addWidget(sys_label)

        self.sys_inst_entry = CustomTextEdit()
        self.sys_inst_entry.append(instruction) # デフォルトのプロンプトを設定
        self.sys_inst_entry.setPlaceholderText("システムインストラクションを入力してください...")
        self.sys_inst_entry.setAcceptRichText(False) # リッチテキストを無効化しておく(コピペすると色がついちゃうから)
        sys_layout.addWidget(self.sys_inst_entry)

        self.apply_btn = QPushButton("適用")
        self.apply_btn.clicked.connect(self.apply_system_instruction)
        self.apply_btn.setFixedWidth(60)
        sys_layout.addWidget(self.apply_btn)

        splitter.addWidget(sys_frame)

        # チャット欄
        self.chat_tabs = QTabWidget()
        
        # HTML
        self.chat_html_view = QWebEngineView()
        self.chat_html_view.setAcceptDrops(True) # ドラッグアンドドロップを有効化しておく
        self.chat_html_view.dragEnterEvent = self.drag_enter_event
        self.chat_html_view.dropEvent = self.drop_event
        self.chat_tabs.addTab(self.chat_html_view, "HTML表示")
        
        # テキスト
        self.chat_text_view = QTextEdit()
        self.chat_text_view.setReadOnly(True) # 書き換えできないようにする
        self.chat_text_view.setAcceptDrops(True) # ドラッグアンドドロップを有効化しておく
        self.chat_text_view.dragEnterEvent = self.drag_enter_event
        self.chat_text_view.dropEvent = self.drop_event
        font = QFont("Courier New", 10)
        font.setFixedPitch(True)
        self.chat_text_view.setFont(font)
        self.chat_tabs.addTab(self.chat_text_view, "テキスト表示")
        
        self.chat_tabs.currentChanged.connect(self.on_tab_changed) # タブ切り替え
        
        splitter.addWidget(self.chat_tabs)

        # 入力欄
        input_frame = QFrame()
        input_layout = QVBoxLayout(input_frame)

        # 入力と送信
        input_row = QHBoxLayout()
        self.user_input = CustomTextEdit()
        self.user_input.setPlaceholderText("メッセージを入力してください... (Ctrl+Enter で送信)")
        self.user_input.setAcceptRichText(False)
        self.user_input.keyPressEvent = self.key_press # キー入力を差し替え（Ctrl+Enterで送信する処理。key_press内でもkeyPressEventを呼んでいるしkeyPressEventは別の場所でオーバーライドしているしもうめちゃくちゃ）
        input_row.addWidget(self.user_input)

        self.send_btn = QPushButton("送信\n(Ctrl+Enter)")
        self.send_btn.clicked.connect(self.send_text)
        self.send_btn.setMaximumWidth(100)
        input_row.addWidget(self.send_btn)

        input_layout.addLayout(input_row)

        # 画面下部のボタンたち
        btn_layout = QHBoxLayout()
        
        btn_layout.addStretch() # ボタンを中央に寄せるためのスペーサー

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

        btn_layout.addStretch()# ボタンを中央に寄せるためのスペーサー

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

        QTimer.singleShot(10, self.update_chat)

    def toggle_theme(self, state):
        self.is_dark_theme = state == Qt.Checked # ダークテーマかどうかの変数を更新
        app = QApplication.instance()
        
        if self.is_dark_theme: # ダークテーマなら
            app.setPalette(self.dark_palette) # パレットをダークテーマに
        else:
            app.setPalette(self.light_palette) # パレットをライトテーマに
        
        self.update_chat() # HTML表示も更新する（こちらはCSSなので別処理）

    def get_html_theme_styles(self):
        # ライトテーマの基本のCSS
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
        # ダークテーマの基本のCSS
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
        # タブの切り替え動作。切り替え時に一回一回表示を更新する
        if index == 0: # HTML
            self.update_chat()
        elif index == 1: # テキスト
            self.update_text()
    
    def set_input_enabled(self, enabled):
        # 入力の可否を切り替える
        # 対象となるウィジェット群
        widgets = [self.user_input, self.send_btn, self.media_btn, self.apply_btn, self.sys_inst_entry]
        for widget in widgets:
            widget.setEnabled(enabled) # 触れるかを切り替える
        
        # 文字を変更する
        if enabled:
            self.send_btn.setText("送信\n(Ctrl+Enter)")
            self.user_input.setPlaceholderText("メッセージを入力してください... (Ctrl+Enter で送信)")
        else:
            self.send_btn.setText("処理中...")
            self.user_input.setPlaceholderText("処理中...")
    
    def drag_enter_event(self, event):
        if not self.is_processing and event.mimeData().hasUrls(): # 処理中でないときかつ、データがファイルパスを持っているときに受け取る
            event.acceptProposedAction()
    
    def drop_event(self, event):
        if self.is_processing:
            return
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.drop_file(file_path) 
    
    def key_press(self, event):
        # 処理中ではない(前半)かつ Ctrl+Enter(後半)
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and (event.modifiers() == Qt.ControlModifier and not self.is_processing):
            self.send_text()
            return
        # 元の関数を呼び出す（カーソル移動についてオーバーライドされている）
        CustomTextEdit.keyPressEvent(self.user_input, event)
    
    def apply_system_instruction(self):
        if not self.is_processing: # 処理中でないとき
            instruction = self.sys_inst_entry.toPlainText().strip()
            self.system_instruction = instruction
            # 新しいインストラクションでモデルを初期化
            self.convo = init_model(self.system_instruction)
            # もろもろリセット
            self.history.clear()
            self.chat_markdown = ""
            self.chat_text_content = ""
            self.add_message("[システム]", "システムインストラクションを更新し、会話をリセットしました。")
            # 入力欄にカーソルを移動
            self.user_input.setFocus()
    
    def update_chat(self):   
        # HTML全体のテンプレート     
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
                        // <a>タグに対してクリック時のイベントを設定
                        document.querySelectorAll("a").forEach(function(link) {{
                            const href = link.getAttribute("href");
                            if (href && href.startsWith("http")) {{
                                link.onclick = function(e) {{
                                    e.preventDefault(); // デフォルトのリンク遷移をやめる
                                    linkHandler.link_click(href); // こっちで定義したリンククリック動作を呼び出し
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
                    // HTML更新時に毎回スクロールがリセットされるのが鬱陶しいので一番下にスクロールするようにする。
                    window.scrollTo(0, document.body.scrollHeight);
                }}, 100);
            </script>
        </body>
        </html>
        """

        if self.chat_markdown:
            # 数式が壊れちゃうのでいろいろやる
            # テキストから、$...$や$$...$$となっている箇所を取り出して、一時的に置き換え
            math_blocks = []

            # 数式おきかえ関数
            def math_replacer(match):
                math_blocks.append(match.group(0))
                return f"@@MATH{len(math_blocks)-1}@@"

            # もどす関数
            def restore_math_expressions(text, blocks):
                for i, expr in enumerate(blocks):
                    text = text.replace(f"@@MATH{i}@@", expr)
                return text

            # コードブロックとそれ以外のテキストに分割する
            # re.splitのセパレータをキャプチャグループ `()` で囲むと、セパレータ自身も結果に含まれる。その結果、partsは次のようになる
            # parts[0] = 最初のコードブロックの前の通常テキスト
            # parts[1] = 最初のコードブロック全体
            # parts[2] = 1番目と2番目のコードブロックの間の通常テキスト
            parts = re.split(r"(```[\s\S]*?```)", self.chat_markdown)

            protected_parts = []
            for i, part in enumerate(parts):
                is_code_block = (i % 2 == 1)

                if is_code_block:
                    # コードブロックは何も処理せず、そのまま追加
                    protected_parts.append(part)
                else:
                    # コードブロックでない部分にのみ、数式保護処理を適用
                    temp_text = part
                    temp_text = re.sub(r"\$\$(.+?)\$\$", math_replacer, temp_text, flags=re.DOTALL) # $$...$$のパターン
                    temp_text = re.sub(r"(?<!\$)\$(.+?)\$(?!\$)", math_replacer, temp_text, flags=re.DOTALL) # $...$のパターン
                    protected_parts.append(temp_text)

            # 全部くっつけちゃう
            protected_markdown = "".join(protected_parts)

            # マークダウンをHTMLに変換
            html_content = markdown.markdown(
                protected_markdown,
                extensions=['fenced_code', 'tables', 'nl2br', 'toc', 'attr_list', 'def_list']
            )

            # 数式を戻す
            html_content = restore_math_expressions(html_content, math_blocks)

            # HTMLタグと属性のホワイトリスト
            allowed_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'b', 'i', 'u', 's', 'strike', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'br', 'span', 'a']
            allowed_attrs = {'*': ['class'], 'a': ['href', 'title'], 'span': ['class']}

            safe_html_content = bleach.clean(html_content, tags=allowed_tags, attributes=allowed_attrs) # bleachでエスケープする。これによってマークダウンの引用やコードブロック内の表示を崩さない
        else: # この分岐なに？？？？？？？？
            html_content = "<p>チャットを開始してください</p>"

        # 現在のテーマに合わせたスタイルを取得
        theme_styles = self.get_html_theme_styles()
        highlight_theme = "atom-one-dark" if self.is_dark_theme else "atom-one-light"
        
        final_html = html_template.format(theme_styles, highlight_theme, safe_html_content)
        self.chat_html_view.setHtml(final_html)
    
    def update_text(self):
        if not hasattr(self, 'chat_text_content'):
            self.chat_text_content = ""
        
        self.chat_text_view.setPlainText(self.chat_text_content)
        # カーソルを一番下へ
        cursor = self.chat_text_view.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_text_view.setTextCursor(cursor)
    
    def regenerate(self):
        # 履歴からテキスト表示を再生成
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

    def add_message(self, sender, text):
        # 新しいメッセージをログに記録して表示を更新する
        # マークダウンに追加
        # 名前とクラス名を紐づけ
        sender_class_map = {
            "[あなた]": "user",
            "[モデル]": "model",
            "[システム]": "system",
            "[エラー]": "error"
        }
        sender_class = sender_class_map.get(sender, "")

        if sender == "[システム]":
             self.chat_markdown += f"#### <span class='{sender_class}'>{sender[1:-1]}</span>\n\n*{text}*\n\n---\n\n"
        elif sender == "[エラー]":
             self.chat_markdown += f"#### <span class='{sender_class}'>{sender[1:-1]}</span>\n\n**{text}**\n\n---\n\n"
        else:
             self.chat_markdown += f"#### <span class='{sender_class}'>{sender[1:-1]}</span>\n\n{text}\n\n---\n\n"

        # テキストに追加
        if not hasattr(self, 'chat_text_content'):
            self.chat_text_content = ""
        
        if sender in ["[あなた]", "[モデル]"]:
            self.chat_text_content += f"{sender}\n{text}\n" + "="*30 + "\n\n"
        else: # システムとエラー
            self.chat_text_content += f"{sender} {text}\n" + "-"*30 + "\n\n"
        
        # 表示を更新
        self.update_chat()
        self.update_text()
    
    def send_text(self):
        if self.is_processing:
            return
        
        message = self.user_input.toPlainText().strip()
        if not message:
            return
        
        self.is_processing = True
        self.set_input_enabled(False) # もろもろを無効化
        
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
        # 会話履歴を更新
        self.history.extend([
            {'role': 'user', 'parts': self.current_worker.message}, 
            {'role': 'model', 'parts': reply}
        ])
    
    def add_error(self, error_msg):
        self.add_message("[エラー]", error_msg)
    
    def processing_finish(self):
        self.is_processing = False
        self.set_input_enabled(True) # もろもろを有効化
        self.user_input.setFocus()
    
    def drop_file(self, file_path):
        # ファイルの送信処理
        def is_text_file(file_path, try_bytes=512):
            # ファイルがテキスト形式かを判定する
            try:
                with open(file_path, 'rb') as f:
                    chunk = f.read(try_bytes)
                if b'\x00' in chunk: # ヌル文字があったらバイナリでいいでしょう
                    return False
                try:
                    chunk.decode('utf-8') # utf-8にできたらいいでしょう
                    return True
                except UnicodeDecodeError:
                    return False # エラーが起きちゃったらバイナリ
            except Exception:
                return False

        if self.is_processing:
            return
        
        # MINEタイプを推測
        mime_type, _ = mimetypes.guess_type(file_path)

        # 対応MIMEタイプを定義
        supported_prefixes = ("image/", "video/", "audio/", "text/")
        supported_exact = ("application/pdf",)

        is_supported = False
        if mime_type:
            if mime_type.startswith(supported_prefixes) or mime_type in supported_exact:
                is_supported = True

        # MIMEタイプが不明でも、テキストファイルならtext/plainとして扱う
        if not is_supported and is_text_file(file_path):
            mime_type = "text/plain"
            is_supported = True
        
        if not is_supported:
            self.add_message("[システム]", f"対応していないメディア形式です: {mime_type or '不明'}")
            return

        self.is_processing = True
        self.set_input_enabled(False)

        user_message = self.user_input.toPlainText().strip()
        self.user_input.clear()
        
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            
            # ユーザーに表示するファイル情報を整形
            file_info = f"**ファイル**: `{os.path.basename(file_path)}` ({mime_type})"
            if user_message:
                file_info += f"\n\n**メッセージ**: {user_message}"
            
            self.add_message("[あなた]", file_info)
            
            # ユーザーに表示するファイル情報を整形
            media_data = {"mime_type": mime_type, "data": file_bytes}
            
            # 非同期処理のためスレッドをわける
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
        
        # 会話履歴を更新。メディアデータはファイルパスとして保存する。が、これだと復元しても会話できなくなるので、困る。base64にでも変換する？うーん
        parts = [{"mime_type": mime_type, "data": f"{file_path}"}]
        if user_message:
            parts.append(user_message)
        
        self.history.append({'role': 'user', 'parts': parts})
        self.history.append({'role': 'model', 'parts': reply})
    
    def send_media(self):
        if self.is_processing:
            return
        
        # ファイル選択ダイアログを表示。テキストファイル追加の関係上、ジャンル分けはやめた
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
        
        # 保存ファイルダイアログを表示
        file_path, _ = QFileDialog.getSaveFileName(
            self, "会話を保存", "", "JSONファイル (*.json)"
        )
        if not file_path:
            return
        
        try:
            # 保存するデータを辞書にまとめる
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
        
        # 読み込みファイルダイアログを表示
        file_path, _ = QFileDialog.getOpenFileName(
            self, "会話を読み込み", "", "JSONファイル (*.json)"
        )
        if not file_path:
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # データ復元
            self.system_instruction = data.get("system_instruction", "")
            self.history = data.get("history", [])
            self.chat_markdown = data.get("chat_markdown", "")
            
            self.regenerate() # テキスト表示用のログを再生成

            self.sys_inst_entry.setPlainText(self.system_instruction)
            # 読み込んだ履歴を引き継いでモデルを再初期化
            self.convo = init_model(self.system_instruction, self.history)
            
            # 表示を更新
            self.update_chat()
            self.update_text()
            
            self.add_message("[システム]", f"会話履歴を読み込みました: `{file_path}`")
        except Exception as e:
            self.add_message("[エラー]", f"読み込みに失敗しました: {e}")
    
    def reset_chat(self):
        if self.is_processing:
            return
        
        # 確認を出す
        reply = QMessageBox.question(
            self, "会話リセット", "会話をリセットしますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # もろもろを初期化
            self.convo = init_model(self.system_instruction)
            self.history.clear()
            self.chat_markdown = ""
            self.chat_text_content = ""
            self.add_message("[システム]", "会話をリセットしました。")
            self.user_input.setFocus()


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