import os
import json
import mimetypes
from dotenv import load_dotenv
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinterdnd2 import DND_FILES, TkinterDnD
import google.generativeai as genai

# ===== APIキー設定 =====
load_dotenv()
api_key = os.getenv("GENAI_API_KEY")
if not api_key:
    raise ValueError("環境変数 GENAI_API_KEY が見つかりません。")
genai.configure(api_key=api_key)

# ===== モデル初期化関数 =====
def init_model(system_instruction="", history_param=None):
    if system_instruction.strip():
        model = genai.GenerativeModel(model_name='gemini-2.0-flash', system_instruction=system_instruction.strip())
    else:
        model = genai.GenerativeModel(model_name='gemini-2.0-flash')
    return model.start_chat(history=history_param or [])

# ===== グローバル変数 =====
system_instruction = ""
convo = init_model(system_instruction)
history = []
modelName = "モデル"

# ===== Tkinter ウィンドウ初期化 =====
window = TkinterDnD.Tk()
window.title("Gemini チャット")
window.geometry("800x720")

# ===== システム命令入力欄 =====
sys_inst_frame = tk.Frame(window)
sys_inst_frame.pack(fill=tk.X, padx=10, pady=5)
tk.Label(sys_inst_frame, text="システム命令:").pack(side=tk.LEFT)
sys_inst_entry = tk.Entry(sys_inst_frame)
sys_inst_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

def apply_system_instruction():
    global convo, history, system_instruction
    instruction = sys_inst_entry.get()
    system_instruction = instruction
    convo = init_model(system_instruction)
    history.clear()
    clear_chat_area()
    display_message("[システム]", "システム命令を更新し、会話をリセットしました。")

apply_inst_btn = tk.Button(sys_inst_frame, text="適用", command=apply_system_instruction)
apply_inst_btn.pack(side=tk.LEFT)

# ===== 会話履歴表示エリア =====
chat_area = scrolledtext.ScrolledText(window, wrap=tk.WORD, state='disabled')
chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

def display_message(sender, text):
    chat_area.configure(state='normal')
    chat_area.insert(tk.END, f"{sender}: {text}\n")
    chat_area.configure(state='disabled')
    chat_area.yview(tk.END)

def clear_chat_area():
    chat_area.configure(state='normal')
    chat_area.delete("1.0", tk.END)
    chat_area.configure(state='disabled')

# ===== 入力欄 + 送信ボタン =====
input_frame = tk.Frame(window)
input_frame.pack(fill=tk.X, padx=10, pady=5)

user_input = tk.Entry(input_frame)
user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

def send_text():
    message = user_input.get().strip()
    if not message:
        return
    user_input.delete(0, tk.END)
    display_message("[あなた]", message)

    try:
        convo.send_message(message)
        reply = convo.last.text
        display_message(f"[モデル]", reply)

        history.append({'role': 'user', 'parts': message})
        history.append({'role': 'model', 'parts': reply})
    except Exception as e:
        display_message("[エラー]", f"{type(e).__name__} - {e}")

send_button = tk.Button(input_frame, text="送信", command=send_text)
send_button.pack(side=tk.RIGHT)

window.bind('<Return>', lambda event: send_text())

# ===== メディア送信 =====
def send_media_file(allowed_types):
    file_path = filedialog.askopenfilename(filetypes=allowed_types)
    if file_path:
        handle_dropped_file(file_path)

def handle_dropped_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type or not (mime_type.startswith(("image/", "video/", "audio/")) or mime_type == "application/pdf"):
        display_message("[システム]", "対応していないメディア形式です。")
        return

    user_message = user_input.get().strip()
    user_input.delete(0, tk.END)

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        display_message("[あなた]", f"<{mime_type}>: {os.path.basename(file_path)}" + (f" + {user_message}" if user_message else ""))

        convo.send_message([
            {"mime_type": mime_type, "data": file_bytes},
            user_message or ""
        ])

        reply = convo.last.text
        display_message("[モデル]", reply)

        parts = [{"mime_type": mime_type, "data": f"{file_path}"}]
        if user_message:
            parts.append(user_message)
        history.append({'role': 'user', 'parts': parts})
        history.append({'role': 'model', 'parts': reply})

    except Exception as e:
        display_message("[エラー]", f"{type(e).__name__} - {e}")

# ===== ドロップ処理の設定 =====
def handle_drop(event):
    file_paths = window.tk.splitlist(event.data)
    for file_path in file_paths:
        if os.path.isfile(file_path):
            handle_dropped_file(file_path)

chat_area.drop_target_register(DND_FILES)
chat_area.dnd_bind('<<Drop>>', handle_drop)

window.drop_target_register(DND_FILES)
window.dnd_bind('<<Drop>>', handle_drop)

# ===== メディア送信ボタン =====
media_frame = tk.Frame(window)
media_frame.pack(pady=5)

tk.Button(media_frame, text="画像を送信", command=lambda: send_media_file([("画像", "*.png *.jpg *.jpeg *.webp *.bmp")])).pack(side=tk.LEFT, padx=5)
tk.Button(media_frame, text="動画を送信", command=lambda: send_media_file([("動画", "*.mp4 *.mov *.webm *.avi")])).pack(side=tk.LEFT, padx=5)
tk.Button(media_frame, text="PDFを送信", command=lambda: send_media_file([("PDF", "*.pdf")])).pack(side=tk.LEFT, padx=5)
tk.Button(media_frame, text="音声を送信", command=lambda: send_media_file([("音声", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg")])).pack(side=tk.LEFT, padx=5)

# ===== 会話保存・読み込み・リセット =====
def save_chat():
    if not history:
        messagebox.showinfo("保存", "保存する会話履歴がありません。")
        return
    path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")])
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"modelName": modelName, "system_instruction": system_instruction, "history": history}, f, ensure_ascii=False, indent=4)
        messagebox.showinfo("保存", f"会話履歴を保存しました:\n{path}")
    except Exception as e:
        messagebox.showerror("保存エラー", f"保存に失敗しました:\n{e}")

def load_chat():
    global convo, history, system_instruction
    path = filedialog.askopenfilename(filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")])
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        system_instruction = data.get("system_instruction", "")
        history = data.get("history", [])
        sys_inst_entry.delete(0, tk.END)
        sys_inst_entry.insert(0, system_instruction)
        convo = init_model(system_instruction, history)
        clear_chat_area()
        for log in history:
            role = "[あなた]" if log['role'] == "user" else "[モデル]"
            parts = log.get('parts')
            if isinstance(parts, list):
                display_parts = []
                for p in parts:
                    if isinstance(p, dict) and 'mime_type' in p:
                        display_parts.append(f"<{p['mime_type']}>")
                    else:
                        display_parts.append(str(p))
                parts_str = " | ".join(display_parts)
            else:
                parts_str = str(parts)
            display_message(role, parts_str)
        display_message("[システム]", "会話履歴を読み込みました。")
    except Exception as e:
        messagebox.showerror("読み込みエラー", f"読み込みに失敗しました:\n{e}")

def reset_chat():
    global convo, history
    if messagebox.askyesno("会話リセット", "会話をリセットしますか？"):
        convo = init_model(system_instruction)
        history.clear()
        clear_chat_area()
        display_message("[システム]", "会話をリセットしました。")

btn_frame = tk.Frame(window)
btn_frame.pack(pady=5)

tk.Button(btn_frame, text="会話を保存", command=save_chat).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="会話を読み込み", command=load_chat).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="会話リセット", command=reset_chat).pack(side=tk.LEFT, padx=5)

# ===== GUI起動 =====
window.mainloop()
