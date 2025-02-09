# Copyright (C) 2024 StarAsh042
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ttkbootstrap import Style
import os
import threading
import queue
import ctypes
import pandas as pd
import webbrowser
import logging
from functools import lru_cache

# 全局配置
LANGUAGES = {
    "cn": {
        "title": "通用表格分割器",
        "input_btn": "选择输入文件",
        "output_btn": "选择输出目录 (可选)",
        "size_label": "每份行数:",
        "format_label": "编号格式:",
        "export_label": "导出格式:",
        "start_btn": "开始分割",
        "cancel_btn": "取消分割",
        "about_btn": "关于",
        "lang_btn": "切换英文",
        "about": "版本: 1.0\n作者: StarAsh042\nGitHub: https://github.com/StarAsh042\n\n使用说明:\n1. 选择要分割的文件\n2. 设置分割参数\n3. 点击开始分割",
        "status_ready": "准备就绪",
        "status_success": "分割完成",
        "status_canceled": "操作已取消",
        "errors": {
            "invalid_file": "不支持的文件格式",
            "invalid_number": "编号格式不正确",
            "missing_dep": "缺少依赖库："
        }
    },
    "en": {
        "title": "Universal Table Splitter",
        "input_btn": "Select Input File",
        "output_btn": "Select Output Directory (Optional)",
        "size_label": "Rows per chunk:",
        "format_label": "Number format:",
        "export_label": "Export format:",
        "start_btn": "Start Splitting",
        "cancel_btn": "Cancel",
        "about_btn": "About",
        "lang_btn": "Switch to Chinese",
        "about": "Version: 1.0\nAuthor: StarAsh042\nGitHub: https://github.com/StarAsh042\n\nUsage:\n1. Select file to split\n2. Set parameters\n3. Click start",
        "status_ready": "Ready",
        "status_success": "Splitting completed",
        "status_canceled": "Operation canceled",
        "errors": {
            "invalid_file": "Unsupported file format",
            "invalid_number": "Invalid number format",
            "missing_dep": "Missing dependency:"
        }
    }
}

SUPPORTED_EXTS = {
    '.csv': {'loader': pd.read_csv, 'formats': ['csv', 'xlsx', 'json', 'html', 'tsv']},
    '.xlsx': {'loader': pd.read_excel, 'formats': ['csv', 'xlsx', 'xls', 'json']},
    '.xls': {'loader': pd.read_excel, 'formats': ['csv', 'xlsx', 'xls', 'json']},
    '.tsv': {'loader': lambda f: pd.read_csv(f, sep='\t'), 'formats': ['csv', 'tsv', 'json']},
    '.json': {'loader': pd.read_json, 'formats': ['json', 'csv', 'xlsx']}
}

EXPORT_FORMATS = {
    'csv': {'writer': 'to_csv', 'ext': '.csv', 'options': {'index': False}},
    'xlsx': {'writer': 'to_excel', 'ext': '.xlsx', 'options': {'index': False, 'engine': 'openpyxl'}},
    'xls': {'writer': 'to_excel', 'ext': '.xls', 'options': {'index': False}},
    'tsv': {'writer': 'to_csv', 'ext': '.tsv', 'options': {'index': False, 'sep': '\t'}},
    'json': {'writer': 'to_json', 'ext': '.json', 'options': {'orient': 'records'}},
    'html': {'writer': 'to_html', 'ext': '.html', 'options': {'index': False}}
}

class SplitStrategy:
    @staticmethod
    def by_sentence(text):
        # 按句子分割实现
        pass  # 添加空语句修复缩进错误
    
    @staticmethod 
    def by_fixed_length(text, chunk_size):
        # 固定长度分割
        pass  # 添加空语句修复缩进错误
        
    @staticmethod
    def by_paragraph(text):
        # 按段落分割
        pass  # 添加缺失的pass语句

def get_splitter(method='sentence'):
    strategies = {
        'sentence': SplitStrategy.by_sentence,
        'fixed': SplitStrategy.by_fixed_length,
        'paragraph': SplitStrategy.by_paragraph
    }
    return strategies.get(method, SplitStrategy.by_sentence)

class UniversalSplitterApp:
    def __init__(self, root):
        self.root = root
        self.current_lang = "cn"
        self.export_format = tk.StringVar(value='csv')
        self.setup_theme()
        self.setup_ui()
        self.center_window()
        self.about_window = None # 关于窗口跟踪

    def setup_theme(self):
        """检测系统主题"""
        try:
            reg = ctypes.windll.shcore
            reg.SetProcessDpiAwareness(1)
            value = ctypes.c_int()
            ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(value), None)
            is_dark = (value.value & 0xff) < 0x80
        except:
            is_dark = False
            
        theme_name = 'darkly' if is_dark else 'litera'
        self.style = Style(theme=theme_name)
        
    def setup_ui(self):
        """初始化界面"""
        self.root.title(LANGUAGES[self.current_lang]['title'])
        self.root.geometry("700x450")
        
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 输入文件
        self.input_entry = self.create_file_selector(
            main_frame, 
            LANGUAGES[self.current_lang]['input_btn'],
            self.choose_input
        )
        
        # 输出目录
        self.output_entry = self.create_file_selector(
            main_frame,
            LANGUAGES[self.current_lang]['output_btn'],
            self.choose_output,
            is_dir=True
        )
        
        # 参数设置
        params_frame = ttk.Frame(main_frame)
        params_frame.pack(pady=10, fill=tk.X)
        
        # 行数设置
        self.size_label = ttk.Label(params_frame, text=LANGUAGES[self.current_lang]['size_label'])
        self.size_label.pack(side=tk.LEFT)
        self.size_entry = ttk.Entry(params_frame, width=10)
        self.size_entry.pack(side=tk.LEFT, padx=5)
        self.size_entry.insert(0, "1000")
        
        # 编号格式
        self.format_label = ttk.Label(params_frame, text=LANGUAGES[self.current_lang]['format_label'])
        self.format_label.pack(side=tk.LEFT, padx=10)
        self.format_entry = ttk.Entry(params_frame, width=10)
        self.format_entry.pack(side=tk.LEFT)
        self.format_entry.insert(0, "001")
        
        # 导出格式
        self.export_label = ttk.Label(params_frame, text=LANGUAGES[self.current_lang]['export_label'])
        self.export_label.pack(side=tk.LEFT, padx=10)
        self.format_combo = ttk.Combobox(params_frame, textvariable=self.export_format, width=12, state="readonly")
        self.format_combo.pack(side=tk.LEFT)
        
        # 进度条
        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress.pack(fill=tk.X, pady=10)
        
        # 状态栏
        self.status = ttk.Label(main_frame, text=LANGUAGES[self.current_lang]['status_ready'])
        self.status.pack()
        
        # 操作按钮
        self.start_btn = ttk.Button(
            main_frame,
            text=LANGUAGES[self.current_lang]['start_btn'],
            command=self.toggle_operation
        )
        self.start_btn.pack(pady=10)
        
        # 底部按钮
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=5)
        
        # 左下角语言切换
        self.lang_btn = ttk.Button(
            bottom_frame,
            text=LANGUAGES[self.current_lang]['lang_btn'],
            command=self.toggle_language
        )
        self.lang_btn.pack(side=tk.LEFT, anchor=tk.SW)
        
        # 右下角关于
        self.about_btn = ttk.Button(
            bottom_frame,
            text=LANGUAGES[self.current_lang]['about_btn'],
            command=self.show_about
        )
        self.about_btn.pack(side=tk.RIGHT, anchor=tk.SE)
        
        # 队列初始化
        self.progress_queue = queue.Queue()
        self.check_queue()
        
    def create_file_selector(self, parent, btn_text, command, is_dir=False):
        """创建文件选择组件"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        
        btn = ttk.Button(frame, text=btn_text, command=command)
        btn.pack(side=tk.LEFT)
        
        entry = ttk.Entry(frame)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        return entry
        
    def choose_input(self):
        """选择输入文件"""
        path = filedialog.askopenfilename(filetypes=[
            ("All Supported Files", list(SUPPORTED_EXTS.keys())),
            ("CSV Files", "*.csv"),
            ("Excel Files", "*.xlsx;*.xls"),
            ("TSV Files", "*.tsv"),
            ("JSON Files", "*.json")
        ])
        
        if path:
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, path)
            
            # 自动设置输出目录
            if not self.output_entry.get():
                output_dir = os.path.dirname(path)
                self.output_entry.insert(0, output_dir)
                
            # 更新导出格式
            ext = os.path.splitext(path)[1].lower()
            available_formats = SUPPORTED_EXTS.get(ext, {}).get('formats', ['csv'])
            self.format_combo['values'] = available_formats
            if self.export_format.get() not in available_formats:
                self.export_format.set(available_formats[0])
                
    def choose_output(self):
        """选择输出目录"""
        path = filedialog.askdirectory()
        if path:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, path)
            
    def toggle_operation(self):
        """开始/取消操作"""
        if hasattr(self, 'running') and self.running:
            self.cancel_operation()
        else:
            self.start_operation()
            
    def start_operation(self):
        """启动分割任务"""
        try:
            input_path = self.input_entry.get()
            output_dir = self.output_entry.get()
            chunk_size = int(self.size_entry.get())
            num_format = self.format_entry.get()
            export_format = self.export_format.get()
            
            if not self.validate_input(input_path, output_dir, chunk_size, num_format, export_format):
                return
                
            self.running = True
            self.update_ui_state(True)
            
            threading.Thread(
                target=self.worker_task,
                args=(input_path, output_dir, chunk_size, num_format, export_format),
                daemon=True
            ).start()
            
        except Exception as e:
            self.show_error(str(e))
            
    def worker_task(self, input_path, output_dir, chunk_size, num_format, export_format):
        """执行分割任务"""
        try:
            ext = os.path.splitext(input_path)[1].lower()
            if ext not in SUPPORTED_EXTS:
                raise ValueError(LANGUAGES[self.current_lang]['errors']['invalid_file'])
                
            # 读取数据
            df = SUPPORTED_EXTS[ext]['loader'](input_path)
            total = len(df)
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            
            # 获取导出配置
            fmt_config = EXPORT_FORMATS[export_format]
            writer = getattr(pd.DataFrame, fmt_config['writer'])
            options = fmt_config['options']
            
            for i, start in enumerate(range(0, total, chunk_size)):
                chunk = df.iloc[start:start+chunk_size]
                suffix = f"{i+1:{num_format}}".zfill(len(num_format))
                output_path = os.path.join(
                    output_dir,
                    f"{base_name}_{suffix}{fmt_config['ext']}"
                )
                
                # 处理特殊格式
                if export_format in ['xlsx', 'xls'] and 'engine' in options:
                    try:
                        writer(chunk, output_path, **options)
                    except ModuleNotFoundError as e:
                        raise RuntimeError(
                            f"{LANGUAGES[self.current_lang]['errors']['missing_dep']} {e.name}"
                        )
                else:
                    writer(chunk, output_path, **options)
                
                self.progress_queue.put(('progress', (start+chunk_size, total)))
                
            self.progress_queue.put(('done', None))
            
        except Exception as e:
            self.progress_queue.put(('error', str(e)))
            
    def validate_input(self, input_path, output_dir, chunk_size, num_format, export_format):
        """验证输入参数"""
        errors = []
        
        if not input_path:
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_file'])
        if not os.path.isfile(input_path):
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_file'])
        if chunk_size <= 0:
            errors.append("Chunk size must be positive")
        if not num_format.isdigit():
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_number'])
        if not output_dir:
            errors.append("Output directory required")
        if export_format not in EXPORT_FORMATS:
            errors.append("Invalid export format")
            
        if errors:
            self.show_error("\n".join(errors))
            return False
        return True
            
    def check_queue(self):
        """处理进度更新"""
        try:
            while True:
                msg_type, data = self.progress_queue.get_nowait()
                
                if msg_type == 'progress':
                    current, total = data
                    self.progress['value'] = current
                    self.progress['maximum'] = total
                    self.status.config(text=f"{current}/{total}")
                elif msg_type == 'done':
                    self.operation_complete()
                elif msg_type == 'error':
                    self.show_error(data)
                    
        except queue.Empty:
            pass
            
        self.root.after(100, self.check_queue)
        
    def operation_complete(self):
        """完成操作"""
        self.running = False
        self.update_ui_state(False)
        self.status.config(text=LANGUAGES[self.current_lang]['status_success'])
        
    def cancel_operation(self):
        """取消操作"""
        self.running = False
        self.update_ui_state(False)
        self.status.config(text=LANGUAGES[self.current_lang]['status_canceled'])
        
    def update_ui_state(self, running):
        """更新界面状态"""
        text = LANGUAGES[self.current_lang]['cancel_btn' if running else 'start_btn']
        self.start_btn.config(text=text)
        self.progress['value'] = 0
        
    def toggle_language(self):
        """切换语言"""
        self.current_lang = "en" if self.current_lang == "cn" else "cn"
        self.update_ui_text()
        
    def update_ui_text(self):
        """更新界面文本"""
        lang = LANGUAGES[self.current_lang]
        
        # 更新标题
        self.root.title(lang['title'])
        
        # 更新按钮
        self.input_entry.master.children['!button'].config(text=lang['input_btn'])
        self.output_entry.master.children['!button'].config(text=lang['output_btn'])
        self.start_btn.config(text=lang['start_btn'])
        self.lang_btn.config(text=lang['lang_btn'])
        self.about_btn.config(text=lang['about_btn'])
        
        # 更新标签
        self.size_label.config(text=lang['size_label'])
        self.format_label.config(text=lang['format_label'])
        self.export_label.config(text=lang['export_label'])
        
        # 更新状态
        if not self.status.cget('text').startswith('Processing'):
            self.status.config(text=lang['status_ready'])
        
    def show_about(self):
        """显示/隐藏关于窗口"""
        if self.about_window and self.about_window.winfo_exists():
            self.about_window.destroy()
            self.about_window = None
        else:
            self.create_about_window()
            
    def create_about_window(self):
        """创建关于窗口"""
        self.about_window = tk.Toplevel(self.root)
        self.about_window.transient(self.root)
        self.about_window.title(LANGUAGES[self.current_lang]['about_btn'])
        
        # 设置窗口位置
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_width = self.root.winfo_width()
        self.about_window.geometry(f"+{main_x + main_width + 10}+{main_y}")
        
        # 创建内容
        text_frame = ttk.Frame(self.about_window)
        text_frame.pack(padx=20, pady=15)
        
        # 可点击的GitHub链接
        def open_github(event):
            webbrowser.open("https://github.com/StarAsh042")
            
        content = LANGUAGES[self.current_lang]['about'].split("\n")
        for line in content:
            if "GitHub" in line:
                lbl = ttk.Label(text_frame, text=line, cursor="hand2", foreground="yellow")
                lbl.bind("<Button-1>", open_github)
            else:
                lbl = ttk.Label(text_frame, text=line)
            lbl.pack(anchor=tk.W)
        
        # 窗口关闭处理
        self.about_window.protocol("WM_DELETE_WINDOW", lambda: self.about_window.destroy())
        
    def update_about_window(self):
        """更新关于窗口内容"""
        if self.about_window and self.about_window.winfo_exists():
            self.about_window.destroy()
            self.create_about_window()
        
    def show_error(self, message):
        """显示错误"""
        self.running = False
        self.update_ui_state(False)
        self.status.config(text=f"Error: {message}")
        
    def center_window(self):
        """窗口居中"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'+{x}+{y}')

@lru_cache(maxsize=128)
def cached_split(text, chunk_size):
    """带缓存的文本分割（适用于重复内容）"""
    # 原有分割逻辑...

def split_text(text, chunk_size=500):
    if not text:
        raise ValueError("输入文本不能为空")
    if chunk_size < 100:
        raise ValueError("块大小不能小于100字符")
        
    try:
        # 原有分割逻辑...
        return chunks
    except Exception as e:
        logger.error(f"文本分割失败: {str(e)}")
        raise TextSplitError(f"文本处理错误: {str(e)}") from e

class TextSplitError(Exception):
    """自定义文本分割异常"""

if __name__ == "__main__":
    root = tk.Tk()
    app = UniversalSplitterApp(root)
    root.mainloop()
