"""自定义控件。

``FileSelector`` 把"按钮 + 输入框"封装成一个持有引用的组件，
替代原先 ``self.input_entry.master.children['!button']`` 那种对 Tk 自动命名规则的隐式依赖
（该写法一旦同一 frame 里再放一个按钮就会 ``KeyError``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import ttk
from typing import Callable


@dataclass
class FileSelector:
    frame: ttk.Frame
    button: ttk.Button
    entry: ttk.Entry
    #: 恢复可编辑状态时使用的 entry 状态：输入框用 readonly（只能通过变量改），输出框用 normal
    entry_state: str = "normal"

    def get(self) -> str:
        return self.entry.get()

    def set(self, value: str) -> None:
        self.entry.configure(state="normal")
        self.entry.delete(0, "end")
        if value:
            self.entry.insert(0, value)
        self.entry.xview_moveto(1.0)  # 长路径时把视图移到文件名
        self.entry.configure(state=self.entry_state)

    def set_button_text(self, text: str) -> None:
        self.button.configure(text=text)

    def set_enabled(self, enabled: bool) -> None:
        self.button.configure(state="normal" if enabled else "disabled")
        self.entry.configure(state=self.entry_state if enabled else "disabled")


def parse_drop_paths(payload: str) -> list[str]:
    """解析 tkinterdnd2 的 ``event.data``。

    为什么不直接用 ``root.tk.splitlist``：Tcl 的列表解析会做反斜杠替换，
    **未加花括号**的 Windows 路径会被破坏（实测 ``C:\\plain\\no\\braces`` 变成
    ``C:plain\\no\\x08races``，``\\b`` 被解释为退格）。tkinterdnd2 只会为含空格的
    路径加花括号，因此相当一部分拖放会静默失效。

    这里自行解析：花括号内的内容原样保留，花括号外按空白切分，反斜杠不做任何处理。
    """
    paths: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in payload:
        if char == "{":
            depth += 1
            if depth == 1:
                buffer = []  # 开始新的一段，丢弃花括号本身
                continue
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    paths.append("".join(buffer))
                    buffer = []
                    continue
        if depth == 0 and char.isspace():
            if buffer:
                paths.append("".join(buffer))
                buffer = []
            continue
        buffer.append(char)
    if buffer:
        paths.append("".join(buffer))
    return [path for path in paths if path]


def build_file_selector(
    parent: ttk.Frame,
    button_text: str,
    command: Callable[[], None],
    entry_state: str = "normal",
    button_width: int = 26,
) -> FileSelector:
    frame = ttk.Frame(parent)
    frame.pack(fill="x", pady=4)
    button = ttk.Button(frame, text=button_text, command=command, width=button_width)
    button.pack(side="left")
    entry = ttk.Entry(frame, state=entry_state)
    entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
    return FileSelector(frame, button, entry, entry_state)
