import os
import json
import mimetypes
import re
from dotenv import load_dotenv
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
from tkinterweb import HtmlFrame
import google.generativeai as genai
import markdown
import time

# APIキー設定
load_dotenv()
api_key = os.getenv("GENAI_API_KEY")
if not api_key:
    raise ValueError("環境変数 GENAI_API_KEY が見つかりません。")
genai.configure(api_key=api_key)

# モデル初期化関数
def init_model(system_instruction="", history_param=None):
    model = genai.GenerativeModel(model_name='gemini-2.0-flash', system_instruction=system_instruction.strip() if system_instruction.strip() else None)
    return model.start_chat(history=history_param or [])

# グローバル変数
system_instruction = ""
convo = init_model(system_instruction)
history = []
modelName = "モデル"
chat_markdown = ""
html_chat = None
html_initialized = False

# Tkinter ウィンドウ初期化
window = TkinterDnD.Tk()
window.title("Gemini チャット (HTML表示)")
window.geometry("900x800")

# システム命令入力欄
sys_inst_frame = tk.Frame(window)
sys_inst_frame.pack(fill=tk.X, padx=10, pady=5)
tk.Label(sys_inst_frame, text="システム命令:").pack(side=tk.LEFT)
sys_inst_entry = tk.Entry(sys_inst_frame)
sys_inst_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

def apply_system_instruction():
    global convo, history, system_instruction, chat_markdown
    instruction = sys_inst_entry.get()
    system_instruction = instruction
    convo = init_model(system_instruction)
    history.clear()
    chat_markdown = ""
    clear_chat_area()
    add_message_to_chat("[システム]", "システム命令を更新し、会話をリセットしました。")

tk.Button(sys_inst_frame, text="適用", command=apply_system_instruction).pack(side=tk.LEFT)

# チャット表示エリア（HTMLのみ）
chat_frame = tk.Frame(window)
chat_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

def initialize_html_frame():
    global html_chat, html_initialized
    if html_initialized:
        return True
    
    try:
        html_chat = HtmlFrame(chat_frame, messages_enabled = False)
        html_chat.pack(padx=5, pady=5, fill=tk.BOTH, expand=True)
        
        # 初期化完了まで少し待つ
        window.update_idletasks()
        time.sleep(0.1)
        
        # ドラッグ&ドロップ設定
        html_chat.drop_target_register(DND_FILES)
        html_chat.dnd_bind('<<Drop>>', handle_drop)
        
        html_initialized = True
        return True
        
    except Exception as e:
        print(f"HtmlFrame初期化エラー: {e}")
        html_initialized = False
        return False

# 起動時にHTML表示を初期化
def initialize_on_startup():
    if initialize_html_frame():
        window.after(100, safe_update_html_display)
    else:
        print("HTML初期化失敗")

# 表示更新
def safe_update_html_display():
    if not html_initialized or html_chat is None:
        return
    
    try:
        # 基本的なHTMLテンプレート
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
                h4 {{ color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
                .user {{ color: #0066cc; }}
                .model {{ color: #009900; }}
                .system {{ color: #666666; font-style: italic; }}
                .error {{ color: #cc0000; }}
                pre {{ background-color: #f8f8f8; padding: 10px; border-radius: 5px; overflow-x: auto; }}
                code {{ background-color: #f0f0f0; padding: 2px 4px; border-radius: 3px; }}
                blockquote {{ border-left: 4px solid #ddd; margin-left: 0; padding-left: 20px; }}
            </style>
        </head>
        <body>
            {}
        </body>
        </html>
        """
        
        # MarkdownをHTMLに変換
        if chat_markdown:
            html_content = markdown.markdown(
                chat_markdown, 
                extensions=['fenced_code', 'tables', 'nl2br']
            )
        else:
            html_content = "<p>チャットを開始してください</p>"
        
        # HTMLを整形
        final_html = html_template.format(html_content)
        # HTMLを読み込み
        html_chat.load_html(final_html)
        # スクロールを最下部に
        def scroll_to_bottom():
            try:
                if html_chat and html_initialized:
                    html_chat.yview_moveto(1.0)
            except:
                pass
        window.after(200, scroll_to_bottom)
        
    except Exception as e:
        print(f"HTML表示更新エラー: {e}")

def update_chat_display():
    # HTML表示の更新
    if html_initialized:
        window.after(50, safe_update_html_display)

def add_message_to_chat(sender, text):
    global chat_markdown
    if sender == "[あなた]":
        chat_markdown += f"#### <span class='user'>あなた</span>\n{text}\n\n"
    elif sender == "[モデル]":
        chat_markdown += f"#### <span class='model'>モデル</span>\n{text}\n\n"
    elif sender == "[システム]":
        chat_markdown += f"#### <span class='system'>システム</span>\n*{text}*\n\n"
    elif sender == "[エラー]":
        chat_markdown += f"#### <span class='error'>エラー</span>\n**{text}**\n\n"
    else:
        chat_markdown += f"#### {sender}\n{text}\n\n"
    update_chat_display()

def clear_chat_area():
    global chat_markdown
    chat_markdown = ""
    update_chat_display()

# 入力・送信
input_frame = tk.Frame(window)
input_frame.pack(fill=tk.X, padx=10, pady=5)
user_input = tk.Entry(input_frame)
user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

def send_text():
    message = user_input.get().strip()
    if not message:
        return
    user_input.delete(0, tk.END)
    add_message_to_chat("[あなた]", message)
    try:
        convo.send_message(message)
        reply = convo.last.text
        add_message_to_chat("[モデル]", reply)
        history.extend([{'role': 'user', 'parts': message}, {'role': 'model', 'parts': reply}])
    except Exception as e:
        add_message_to_chat("[エラー]", f"{type(e).__name__} - {e}")

tk.Button(input_frame, text="送信", command=send_text).pack(side=tk.RIGHT)
window.bind('<Return>', lambda event: send_text())

# ドラッグ＆ドロップ メディア処理
def handle_dropped_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type or not (mime_type.startswith(("image/", "video/", "audio/")) or mime_type == "application/pdf"):
        add_message_to_chat("[システム]", "対応していないメディア形式です。")
        return

    user_message = user_input.get().strip()
    user_input.delete(0, tk.END)
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        file_info = f"**ファイル**: `{os.path.basename(file_path)}` ({mime_type})"
        if user_message:
            file_info += f"\n\n**メッセージ**: {user_message}"
        add_message_to_chat("[あなた]", file_info)

        convo.send_message([
            {"mime_type": mime_type, "data": file_bytes},
            user_message or ""
        ])
        reply = convo.last.text
        add_message_to_chat("[モデル]", reply)

        parts = [{"mime_type": mime_type, "data": f"{file_path}"}]
        if user_message:
            parts.append(user_message)
        history.append({'role': 'user', 'parts': parts})
        history.append({'role': 'model', 'parts': reply})
    except Exception as e:
        add_message_to_chat("[エラー]", f"{type(e).__name__} - {e}")

def handle_drop(event):
    file_paths = window.tk.splitlist(event.data)
    for file_path in file_paths:
        if os.path.isfile(file_path):
            handle_dropped_file(file_path)

# ウィンドウレベルでのドラッグ&ドロップ設定
window.drop_target_register(DND_FILES)
window.dnd_bind('<<Drop>>', handle_drop)

# メディア送信ボタン
media_frame = tk.Frame(window)
media_frame.pack(pady=5)
tk.Button(media_frame, text="画像を送信", command=lambda: send_media_file([("画像", "*.png *.jpg *.jpeg *.webp *.bmp")])).pack(side=tk.LEFT, padx=5)
tk.Button(media_frame, text="動画を送信", command=lambda: send_media_file([("動画", "*.mp4 *.mov *.webm *.avi")])).pack(side=tk.LEFT, padx=5)
tk.Button(media_frame, text="PDFを送信", command=lambda: send_media_file([("PDF", "*.pdf")])).pack(side=tk.LEFT, padx=5)
tk.Button(media_frame, text="音声を送信", command=lambda: send_media_file([("音声", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg")])).pack(side=tk.LEFT, padx=5)

def send_media_file(allowed_types):
    file_path = filedialog.askopenfilename(filetypes=allowed_types)
    if file_path:
        handle_dropped_file(file_path)

# 会話保存・読み込み・リセットなど
def save_chat():
    if not history:
        messagebox.showinfo("保存", "保存する会話履歴がありません。")
        return
    path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSONファイル", "*.json")])
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"modelName": modelName, "system_instruction": system_instruction, "history": history, "chat_markdown": chat_markdown}, f, ensure_ascii=False, indent=4)
        add_message_to_chat("[システム]", f"会話履歴を保存しました: `{path}`")
    except Exception as e:
        add_message_to_chat("[エラー]", f"保存に失敗しました: {e}")

def load_chat():
    global convo, history, system_instruction, chat_markdown
    path = filedialog.askopenfilename(filetypes=[("JSONファイル", "*.json")])
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        system_instruction = data.get("system_instruction", "")
        history = data.get("history", [])
        chat_markdown = data.get("chat_markdown", "")

        sys_inst_entry.delete(0, tk.END)
        sys_inst_entry.insert(0, system_instruction)
        convo = init_model(system_instruction, history)
        update_chat_display()
        add_message_to_chat("[システム]", f"会話履歴を読み込みました: `{path}`")
    except Exception as e:
        add_message_to_chat("[エラー]", f"読み込みに失敗しました: {e}")

def reset_chat():
    global convo, history, chat_markdown
    if messagebox.askyesno("会話リセット", "会話をリセットしますか？"):
        convo = init_model(system_instruction)
        history.clear()
        chat_markdown = ""
        clear_chat_area()
        add_message_to_chat("[システム]", "会話をリセットしました。")

btn_frame = tk.Frame(window)
btn_frame.pack(pady=5)
tk.Button(btn_frame, text="会話を保存", command=save_chat).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="会話を読み込み", command=load_chat).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="会話リセット", command=reset_chat).pack(side=tk.LEFT, padx=5)

# 起動時のメッセージ
add_message_to_chat("[システム]", "Geminiチャットへようこそ。")

# HTML表示の初期化
window.after(500, initialize_on_startup)

# GUI起動
window.mainloop()