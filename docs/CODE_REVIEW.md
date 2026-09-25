# Universal Table Splitter 代码质量评估报告

> 评估对象：`d:/GitHub/Universal_Table_Splitter`（`splitter.py` 518 行、`README.md`、`requirements.txt`、`LICENSE`、`.gitignore`）
> 评估环境：Windows / Python 3.10.11 / pandas 2.3.3
> 评估维度：代码结构、性能、安全性、可读性、可维护性、错误处理、测试覆盖、文档与工程化

> **实施状态（1.1.0）**：本报告的三个阶段已全部落地，详见 [../CHANGELOG.md](../CHANGELOG.md)。
> 项目已从单文件拆分为 `universal_table_splitter`（`core` 业务层 + `ui` 界面层），
> 所有 P0/P1/P2 缺陷均已修复并配有回归用例；本文档保留为本次重构的评估依据与验收清单。
>
> 补充（2026-09-25）：文中建议的「CI 三平台测试矩阵」已实现后又按需求移除——
> 现在 GitHub Actions **只做打包与发布**（见 [RELEASE.md](RELEASE.md)），
> `ruff` 与 `pytest` 改为在本地/pre-commit 中执行。

---

## 0. 总体结论

项目定位清晰（单文件 GUI 表格分割工具），核心功能可用，i18n 与主题适配是有价值的差异化设计。但它目前处于**"可运行的原型"**状态，而非**"可发布的产品"**：存在多处**已实测确认的功能性缺陷**（取消失效、`.xls` 导出 100% 失败、拖放含空格路径失败）、**数据保真度风险**（编码、类型推断）以及**零测试、零日志、零打包配置**的工程化空白。

| 维度 | 评分 | 说明 |
|---|---|---|
| 代码结构 | 4/10 | 518 行单文件混合 UI/配置/i18n/业务逻辑，存在未使用的死代码类 |
| 性能 | 6/10 | 小文件无问题；全量入内存读取，大文件会 OOM |
| 安全性 | 5/10 | 无远程/权限攻击面，但存在 CSV 公式注入、解压炸弹、静默覆盖等风险 |
| 可读性 | 5/10 | 命名尚可，但混入硬编码英文错误串、字符串嗅探式解析、魔法数 |
| 可维护性 | 4/10 | 脆弱 widget 查找、`hasattr` 状态管理、字符串式调度、无类型注解 |
| 错误处理 | 4/10 | 裸 `except`、宽泛 `except Exception`、错误信息重复/泄露内部实现 |
| 测试覆盖 | 0/10 | 无任何测试、无 CI、无 lint/类型检查配置 |
| 文档 | 5/10 | README 结构好，但**与实现存在 3 处直接矛盾** |

**核心判断**：优先修复 3 个 P0 缺陷 + 数据保真问题（约半天工作量，收益最大），再做"核心逻辑与 UI 解耦"重构（1–2 天），最后补测试/打包/CI（1 天）。

---

## 1. 已完成验证的缺陷清单（按严重度排序）

所有标 ✅ 实测 的条目均在本机复现确认，非推测。

### P0-1 ✅ 取消功能完全不生效，且会引发并发写文件导致输出损坏

```357:410:splitter.py
def validate_input(self, input_path, output_dir, chunk_size, num_format, export_format):
...
    def cancel_operation(self):
        """取消操作"""
        self.running = False
        self.update_ui_state(False)
        self.status.config(text=LANGUAGES[self.current_lang]['status_canceled'])
```

**问题**：
1. `cancel_operation` 只把 `self.running = False` 并把按钮文案改回"开始分割"，**从未通知工作线程停止**。`worker_task` 的 `for` 循环里没有任何取消检查点，线程会继续把剩余分块全部写完。
2. 由于 `self.running` 已为 `False`，用户再次点击"开始分割"时 `toggle_operation`（283–288 行）会**启动第二个线程**，与仍在运行的第一个线程**并发写入同名文件**。磁盘上会得到内容错乱/截断的文件——这是**数据损坏级**问题，而非体验问题。
3. 取消后 `progress_queue` 仍持续投递 `progress` 消息，UI 会继续刷新被取消任务的进度，状态与真实情况不一致。

**修复方案**：引入协作式取消令牌，并禁止重入。

```python
# __init__
self._cancel_event = threading.Event()
self._worker: threading.Thread | None = None

def start_operation(self):
    if self._worker and self._worker.is_alive():
        self.show_error("任务仍在运行中")   # 双保险，避免重入
        return
    self._cancel_event.clear()
    self._worker = threading.Thread(
        target=self.worker_task,
        args=(job, self._cancel_event),
        daemon=True,
    )
    self._worker.start()

def cancel_operation(self):
    self._cancel_event.set()          # 仅发出信号，UI 状态由 worker 回执后统一更新

# worker_task 内层循环
for index, (start, stop) in enumerate(plan_chunks(total, job.chunk_size), start=1):
    if cancel.is_set():
        self.progress_queue.put(("canceled", written_paths))
        return
    ...
```

**同时建议**：取消后询问用户是否删除已生成的半成品文件（见 P1-6 的原子写入方案）。

---

### P0-2 ✅ `.xls` 导出 100% 失败（pandas 2.x 已移除 xlwt 写入引擎）

```89:96:splitter.py
EXPORT_FORMATS = {
    'csv': {'writer': 'to_csv', 'ext': '.csv', 'options': {'index': False}},
    'xlsx': {'writer': 'to_excel', 'ext': '.xlsx', 'options': {'index': False, 'engine': 'openpyxl'}},
    'xls': {'writer': 'to_excel', 'ext': '.xls', 'options': {'index': False}},
```

**实测结果**（pandas 2.3.3）：

```
>>> pd.DataFrame({'a':[1]}).to_excel('t.xls', index=False)
ValueError: No engine for filetype: 'xls'
```

**问题**：`requirements.txt` 声明 `pandas>=2.0.3`，而 pandas 2.0 起已移除 `xlwt` 写入支持，`xls` 不在默认写入器映射中。因此当用户选择 `.xlsx`/`.xls` 输入并选择 `xls` 导出时（`SUPPORTED_EXTS` 第 83–84 行的 `formats` 列表首项就是 `csv`，但 `xls` 确实在候选中），**必然抛异常**，且错误被 355 行捕获后以 `ValueError: No engine for filetype: 'xls'` 原样显示在状态栏——用户完全无法理解。

**修复方案**：删除 `xls` 导出选项（推荐），并同步移除 `SUPPORTED_EXTS` 中 `.xlsx`/`.xls` 的 `'xls'` 候选值；README 第 11 行的"XLSX"表述保留即可。

> 备选：若必须支持 `.xls`，需自行转写为 OLE2 格式（引入 `xlwt` 已不可行），成本远高于收益，不建议。

---

### P0-3 ✅ 拖放包含空格的路径会被截断并静默失效

```501:514:splitter.py
    def handle_drop(self, event):
        """处理拖放文件"""
        files = event.data.split()
        if files:
            path = files[0].strip("{}")
```

**问题**：tkinterdnd2 的 `event.data` 对**含空格的路径会加花括号包裹**（如 `{C:/Program Files/a.csv}`），且多文件时以空格分隔。`str.split()` 会把它切成 `['{C:/Program', 'Files/a.csv}']`，取 `files[0]` 得到 `{C:/Program`，`os.path.isfile()` 为 `False`，于是**静默什么都不做**——用户拖放了但没反应，也无任何提示。这是拖放功能最常见的失败模式。

**修复方案**：使用 Tk 自带的列表解析器，它能正确处理花括号与空格：

```python
def handle_drop(self, event):
    paths = self.root.tk.splitlist(event.data)
    if not paths:
        return
    path = paths[0]
    if not os.path.isfile(path):
        self.show_error(tr("err.not_a_file", path=path))
        return
    self._apply_input_file(path)      # 与 choose_input 共用同一逻辑
```

**连带问题**：`handle_drop`（509–514 行）与 `choose_input`（260–269 行）重复实现了"自动填输出目录 + 刷新格式下拉 + 校正当前格式"三件事，应抽取为 `_apply_input_file(path)` 单一入口（DRY）。另外 `handle_drop` 会**无条件覆盖**用户已手工选择的输出目录。

---

### P1-1 ✅ 中文输出乱码：`to_csv` 默认写无 BOM 的 UTF-8

**实测**：`df.to_csv('a.csv', index=False)` 写入字节为 `b'\xe5\x90\x8d\xe7\xa7\xb0...'`，即 **UTF-8 无 BOM**。在中文 Windows 上，Excel 默认按 GBK 打开 CSV，中文列名/内容会显示为乱码。对一个面向中文用户的表格工具而言，这是高频投诉点。

**修复**：CSV/TSV 导出统一使用 `encoding='utf-8-sig'`（带 BOM，Excel 可自动识别），或提供"CSV 编码"选项（`utf-8-sig` / `gbk`）。

```python
'csv': {'writer': 'to_csv', 'ext': '.csv',
        'options': {'index': False, 'encoding': 'utf-8-sig'}},
'tsv': {'writer': 'to_csv', 'ext': '.tsv',
        'options': {'index': False, 'sep': '\t', 'encoding': 'utf-8-sig'}},
```

---

### P1-2 ✅ GBK 编码的 CSV **直接读取失败**，无编码回退

**实测**：`pd.read_csv('gbk文件.csv')` → `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc3 ...`。

**问题**：`SUPPORTED_EXTS['.csv']['loader'] = pd.read_csv` 采用默认 `encoding='utf-8'`。国内大量业务导出的 CSV 是 GBK/GB18030，用户会直接收到一个英文 `UnicodeDecodeError` 堆栈字符串。

**修复**：为 CSV/TSV 增加编码探测回退（`utf-8-sig` → `gbk`/`gb18030` → `utf-16` → `latin-1` 兜底并提示），并把探测结果回写到状态栏便于用户确认。

```python
_CSV_ENCODINGS = ("utf-8-sig", "gb18030", "utf-16", "latin-1")

def read_csv_with_fallback(path, **kw):
    for enc in _CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, **kw), enc
        except UnicodeDecodeError:
            continue
    raise AppError("err.encoding", path=path)
```

---

### P1-3 数据保真度风险：类型推断会破坏 ID / 编号列

`pd.read_csv` / `pd.read_excel` 默认做类型推断，会导致**静默的数据失真**，这对"分割器"这类搬运工具是致命的：

- 前导零丢失：`"00123"` → `123`
- 长数字变科学计数法 / 精度丢失：`"138001380001234567890"` → `1.3800138000123457e+20`
- 空值统一为 `NaN`，导出 CSV 时变成空串，导出 Excel 时单元格类型改变
- 日期字符串被自动解析成 `datetime`，导出后格式与原文不同
- 整数列出现空值 → 整列升为 `float`，导出为 `1.0` 而非 `1`

**建议**：在界面上增加**"按文本读取（保真模式，默认开启）"**复选框，勾选时以 `dtype=str, keep_default_na=False` 读取，最大化保持原样；关闭时保留原有自动推断行为。

```python
read_kw = {"dtype": str, "keep_default_na": False} if fidelity_mode else {}
```

---

### P1-4 仅处理 Excel 首个工作表，其余 sheet 被静默丢弃

`pd.read_excel` 默认 `sheet_name=0`。对于多 sheet 的 `.xlsx`，用户会误以为"分割了整张表"，实际只分割了第一张。建议：读取时先探测 sheet 列表，单 sheet 直接处理，多 sheet 时弹窗让用户选择（或提供"全部导出"模式），并在 README 中明确说明。

---

### P1-5 大文件全量载入内存，存在 OOM 风险

```321:322:splitter.py
            # 读取数据
            df = SUPPORTED_EXTS[ext]['loader'](input_path)
```

- CSV/TSV：`pd.read_csv` 会把整表读入内存。一个 500MB 的 CSV 在 pandas 中通常膨胀 3–5 倍（≈2GB+），加上分块切片拷贝，极易触发 `MemoryError`。
- Excel：`pd.read_excel` 本身即全量解析，且 openpyxl 解析大 xlsx 的峰值内存更夸张。
- `read_excel` 处理恶意构造的 xlsx 还存在**解压炸弹**风险（小文件解压出巨量数据）。
- 无任何文件大小预检与提示。

**修复方案（按优先级）**：

1. **CSV/TSV 流式分块读取**，从根上消除内存问题：

```python
reader = pd.read_csv(path, chunksize=job.chunk_size, **read_kw)
for index, chunk in enumerate(reader, start=1):
    if cancel.is_set():
        break
    write_chunk(chunk, index)
```

2. **Excel 只读流式**：`openpyxl.load_workbook(path, read_only=True)` 按行迭代，手工组块。
3. **前置预检**：读取前检查文件大小与（xlsx 的）zip 解压比，超过阈值给出确认提示。
4. 为 `MemoryError` 单独捕获并给出可操作提示（"文件过大，建议先另存为 CSV 再分割"）。

---

### P1-6 失败/取消会留下不完整的半成品文件，且无原子写入

当前逐个直接写入最终路径，若第 3 个分块因磁盘满/权限被拒/依赖缺失失败，前 2 个文件已落盘，用户无法区分"完整的输出"与"残缺的输出"。

**修复**：先写临时文件再原子重命名，失败时统一清理。

```python
tmp_path = os.path.join(output_dir, f".{base}_{suffix}.part{spec.ext}")
spec.write(chunk, tmp_path)          # 末位扩展名保持不变，pandas 才能正确推断引擎
os.replace(tmp_path, output_path)    # 同分区原子替换
```

配套在 `except` 分支中 `os.remove(tmp)` 并回滚已生成的输出（或明确提示"已生成 N 个文件，未完成"）。

---

### P1-7 编号格式的语义与文档/校验三方不一致，且缺少长度上界

```184:189:splitter.py
        self.format_entry = ttk.Entry(params_frame, width=10)
        self.format_entry.pack(side=tk.LEFT)
        self.format_entry.insert(0, "001")
...
        if not num_format.isdigit():
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_number'])
```

**实测确认的三个问题**：

1. **文档与实现矛盾**：README 第 46 行指导用户"使用Python格式字符串（如 `03d` 生成001,002）"，但 `'03d'.isdigit()` 为 `False` → 会被 `invalid_number` 拒绝。用户按文档操作必然失败。
2. **格式串语义其实是"位数"**：`f"{5:001}"` 实测结果为 `'5'`（`0` 被当作填充标志、宽度被解析为 `1`），真正生效的是末尾 `.zfill(len(num_format))`。也就是说 `num_format` 实际只被使用为"目标宽度"，而不是格式说明符——写成 `{i:<num_format>}` 是**误导性实现**，应改为 `str(i).zfill(digits)`。
3. **无长度上界**：`f"{1:1000}"` 会生成 **1000 字符**的字符串（实测长度 1000），拼进文件名后远超 Windows 260 字符路径限制 → 必然 `OSError`。`isdigit()` 校验完全挡不住。

**修复**：

```python
MIN_DIGITS, MAX_DIGITS = 1, 10
digits = len(num_format)
if not num_format.isdigit() or not (MIN_DIGITS <= digits <= MAX_DIGITS):
    raise AppError("err.invalid_number")

def format_suffix(index: int, digits: int) -> str:
    return str(index).zfill(digits)     # 索引超出位数时自然增宽，如 1000, 1001
```

同时把 README 的 `03d` 描述改为 `001`（位数）语义。

---

### P2-1 ✅ 文件恰好被重复校验，同一错误提示两次

```361:364:splitter.py
        if not input_path:
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_file'])
        if not os.path.isfile(input_path):
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_file'])
```

`input_path` 为空时，`os.path.isfile("")` 也是 `False` → "不支持的文件格式"会被追加两次，用户看到重复两行的错误提示。

---

### P2-2 非数字行数输入会向用户暴露 Python 内部异常

```292:312:splitter.py
        try:
            input_path = self.input_entry.get()
            ...
            chunk_size = int(self.size_entry.get())
            ...
        except Exception as e:
            self.show_error(str(e))
```

当用户输入 `abc` 或留空时，`int()` 抛 `ValueError`，被宽泛 `except` 捕获后直接 `str(e)` 显示：
`Error: invalid literal for int() with base 10: 'abc'` —— 未本地化、面向开发者、无法指导用户。

**修复**：把 `int()` 转换移入参数解析层并抛出带 i18n key 的 `AppError`；`except Exception` 应只用于兜底，且必须 `logging.exception()` 记录完整堆栈，对用户只显示友好文案 + "查看日志"。

---

### P2-3 校验逻辑缺陷：输出目录未做存在性/可写性检查

`validate_input` 只检查 `not output_dir`（空串），不检查：
- 目录是否存在（不存在时下游 `open()` 抛 `FileNotFoundError`）
- 是否有写权限
- 是否与输入文件同目录且格式相同（可能覆盖源文件）
- 是否已存在同名输出（**静默覆盖**，无任何确认）

**修复**：`os.makedirs(output_dir, exist_ok=True)` + `os.access(output_dir, os.W_OK)`，并在预检阶段计算全部目标文件名，若有冲突则弹窗询问"覆盖/跳过/自动加序号"。

---

### P2-4 参数硬约束未落实（README 承诺 1–10000 行）

README 第 10/45 行声称"支持自定义行数（1-10000）"，代码中除 `chunk_size <= 0` 外**无任何上界校验**，也没有"分块数量"预警。若用户填 `1`（100 万行数据），会产生 100 万个文件、100 万次磁盘写入、100 万条队列消息，UI 处理队列时可能长时间假死。

**修复**：增加上界校验（1～1,000,000 可配置），并在预估输出文件数 > 1000 时给出确认提示。

---

### P2-5 进度计算越界 + 完成后进度条被清零

```350:352:splitter.py
                self.progress_queue.put(('progress', (start+chunk_size, total)))
```

- 末块越界：`total=2500, chunk_size=1000` 时最后投递 `3000/2500`，状态栏显示错误的 `3000/2500`。应使用 `min(stop, total)` 或直接使用 `stop`。
- `update_ui_state(False)`（412–416 行）会把 `progress['value']` 重置为 `0`，因此**任务完成后进度条是空的**，用户看不到 100% 的完成反馈。建议完成时置为 100%，并在下一任务开始时才重置。

---

### P2-6 空表/零行输入无任何反馈

`total == 0` 时 `for` 循环不执行，直接投递 `done`，用户看到"分割完成"但目录里没有任何文件，会误判为失败。应显式提示"输入文件无数据行"。

---

## 2. 代码结构问题

### 2-1 死代码：`SplitStrategy` 与 `get_splitter` 从未被调用

```98:120:splitter.py
class SplitStrategy:
    @staticmethod
    def by_sentence(text):
        # 按句子分割实现
        pass
    ...
def get_splitter(method='sentence'):
    ...
```

三个 `pass` 空实现 + 全局工厂函数属于 git 历史 `9fb9fee "Enhance README and add text splitting utilities"` 的遗留物，**与表格分割功能毫无关系，零调用点**。空实现的 `by_sentence(text)` 连 `pass` 都没有（只有注释），若被误调用会返回 `None` 而不报错。

**处理**：直接删除。若确有文本分割规划，移到独立的 `text_split.py` 并配套测试与开关，不要以空壳形式留在主路径上。

### 2-2 未使用的导入

- `import logging`（第 25 行）：全文零处使用 —— 而项目恰恰**最需要日志**（见 §6）。
- `from functools import lru_cache`（第 26 行）：零处使用。
- `import webbrowser`：仅用于打开 About 里的 GitHub 链接，可用 `ttk` 的按钮替代，属可接受用法。

**处理**：删除 `logging`/`lru_cache`，或（推荐）真正引入 `logging` 并替换掉"错误信息塞进状态栏"的做法。

### 2-3 模块级副作用：`root = TkinterDnD.Tk()` 在导入时创建窗口

```29:33:splitter.py
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    root = TkinterDnD.Tk()
except ImportError:
    root = tk.Tk()
```

导入 `splitter.py` 即创建 GUI 窗口，导致：
- **无法导入即测试**（pytest 收集阶段会弹窗/报 `TclError`），这是当前零测试的隐性根因之一；
- 无法在文件中复用模块；
- 与 `setup_theme` 中的 DPI 设置存在**顺序倒置**（见下条）。

**处理**：把窗口创建移入 `def main()`，模块级只保留纯配置。

### 2-4 DPI 感知设置时机错误（HiDPI 模糊）

```135:147:splitter.py
    def setup_theme(self):
        """检测系统主题"""
        try:
            reg = ctypes.windll.shcore
            reg.SetProcessDpiAwareness(1)
```

`Tk()` 已在模块导入时创建（第 31/33 行），而 `SetProcessDpiAwareness` 在 `__init__` 中才调用——**必须在创建任何窗口之前调用**，否则高分屏下窗口会被系统拉伸导致模糊。另外：
- Windows 10 1703+ 推荐 `SetProcessDpiAwarenessContext(-4)`（Per-Monitor V2）；
- 108 行处还在 `setup_theme` 里做了跟"主题"无关的 DPI 设置，职责混淆。

**处理**：抽到 `main()` 最开头执行：

```python
def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-Monitor DPI Aware
    except (AttributeError, OSError):
        pass
```

### 2-5 主题探测方式不可靠，且非 Windows 平台完全失效

```140:144:splitter.py
            value = ctypes.c_int()
            ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(value), None)
            is_dark = (value.value & 0xff) < 0x80
        except:
            is_dark = False
```

- `DwmGetColorizationColor` 返回的是**强调色/标题栏颜色**，不是"应用深色模式"开关。判断 `& 0xff < 0x80` 依据蓝色通道分量，与深色模式没有稳定因果关系，很多强调色下会判断错误。
- 正确来源是注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize` 下的 `AppsUseLightTheme`。
- **非 Windows 平台**（README 明确宣称跨平台）此处必然异常 → 永远落入浅色主题，macOS 深色模式、Linux GTK 深色主题均不支持。
- 裸 `except:`（143 行）还会吞掉一切错误（含 `KeyboardInterrupt`），是 flake8/Bandit 直接报告的反模式。

**修复**：

```python
def detect_dark_mode() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2)
            return "Dark" in out.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    return False
```

同时把 `except:` 全部改为 `except Exception:` 并 `logging.debug(...)` 记录。

### 2-6 字符串式的自适应调度，缺少适配器抽象

```81:96:splitter.py
SUPPORTED_EXTS = {
    '.csv': {'loader': pd.read_csv, 'formats': [...]},
    ...
}
EXPORT_FORMATS = {
    'csv': {'writer': 'to_csv', 'ext': '.csv', 'options': {...}},
```

- `writer` 存**方法名字符串**，运行时 `getattr(pd.DataFrame, ...)` 反射调用，静态检查无法发现 typo，重构无保护。
- `loader` 用 lambda 处理 TSV，`formats` 列表散落各处，新增格式需同时改 3 处（`SUPPORTED_EXTS`、`EXPORT_FORMATS`、可能的 `handle_drop` 逻辑）。
- `EXPORT_FORMATS` 是模块级可变字典，`options` 被 `**options` 直接展开传递；一旦某处误改（如按需 pop 掉 `engine`）会污染全局。
- README 第 9 行声称输入支持 HTML，但 `SUPPORTED_EXTS` 中**没有 `.html`** → 纯文档错误。

**修复**：用不可变规格对象 + 可调用对象替代字符串反射：

```python
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable

@dataclass(frozen=True)
class ExportSpec:
    ext: str
    write: Callable[[pd.DataFrame, str], None]

EXPORT_FORMATS = MappingProxyType({
    "csv":  ExportSpec(".csv",  lambda df, p: df.to_csv(p, index=False, encoding="utf-8-sig")),
    "tsv":  ExportSpec(".tsv",  lambda df, p: df.to_csv(p, index=False, sep="\t", encoding="utf-8-sig")),
    "xlsx": ExportSpec(".xlsx", lambda df, p: df.to_excel(p, index=False, engine="openpyxl")),
    "json": ExportSpec(".json", lambda df, p: df.to_json(p, orient="records", force_ascii=False)),
    "html": ExportSpec(".html", lambda df, p: df.to_html(p, index=False)),
})   # 注意：已移除不可用的 xls
```

> 注意 JSON 导出的 `force_ascii=False` —— 当前 `to_json` 默认 `force_ascii=True`，中文会被写成 `\uXXXX` 转义，虽然 JSON 语义正确但可读性差，建议显式关闭。

### 2-7 `update_ui_text` 依赖自动生成的 widget 名（脆弱但当前可用）

```427:428:splitter.py
        self.input_entry.master.children['!button'].config(text=lang['input_btn'])
        self.output_entry.master.children['!button'].config(text=lang['output_btn'])
```

**实测确认**：当前 `children` 键确实为 `['!button', '!entry']`，所以**现在能正常工作**。但这是对 Tk 自动命名规则的隐式依赖：
- 一旦 `create_file_selector` 里在按钮之外/之前再添加任何 `ttk.Button`，键会变成 `!button2`，**语言切换直接抛 `KeyError`**；
- 与 `!entry` 的存在顺序、`create_file_selector` 的内部实现强耦合。

**修复**：`create_file_selector` 返回 `(entry, button)` 或用一个小的 `FileSelector` 组件类持有引用：

```python
@dataclass
class FileSelector:
    frame: ttk.Frame
    button: ttk.Button
    entry: ttk.Entry

    def set_text(self, text: str) -> None:
        self.button.config(text=text)
```

### 2-8 状态管理用 `hasattr` 打补丁

```285:288:splitter.py
        if hasattr(self, 'running') and self.running:
```

`running` 未在 `__init__` 初始化，靠 `hasattr` 规避 `AttributeError`。这是"状态机缺失"的表征。建议：

```python
class AppState(enum.Enum):
    IDLE = auto(); RUNNING = auto(); CANCELLING = auto()

self.state = AppState.IDLE          # __init__ 中显式初始化
self.export_format = tk.StringVar(value="csv")
self.size_var = tk.StringVar(value="1000")
self.format_var = tk.StringVar(value="001")
```

顺带把 `size_entry.insert(0, "1000")`（182 行）这类"先建控件再塞值"改为直接绑定 `textvariable`，同时天然解决"下次打开无法记住上次参数"的问题。

### 2-9 关于窗口的解析方式脆弱，且浅色主题下不可见

```465:472:splitter.py
        content = LANGUAGES[self.current_lang]['about'].split("\n")
        for line in content:
            if "GitHub" in line:
                lbl = ttk.Label(text_frame, text=line, cursor="hand2", foreground="yellow")
```

- 用**字符串内容嗅探**（`"GitHub" in line`）来决定是否渲染成可点击链接，改文案即破坏功能。
- `foreground="yellow"` 硬编码：`litera`（浅色）主题下黄字几乎不可见。
- 把整个 `about` 大文本拆行渲染，无法单独更新版本号；版本号硬编码在 i18n 字符串里（第 48/69 行），**与代码版本无单一事实来源**。

**修复**：i18n 中拆分为结构化字段（`version`、`author`、`url`），UI 用 `ttk.Label` + 明确的链接控件与主题感知样式（如 `style="Link.TLabel"`）。

### 2-10 `show_about` 的"再点一次即关闭"行为反直觉

```438:444:splitter.py
    def show_about(self):
        if self.about_window and self.about_window.winfo_exists():
            self.about_window.destroy()
```

用户点"关于"期望聚焦/显示窗口，实际却把它关掉了。另外 `about_window` 关闭后引用未置 `None`（依赖 `winfo_exists()` 兜底），逻辑绕。建议：不存在则创建、存在则 `lift()` + `focus_force()`。

### 2-11 `update_ui_text` 中的语言守卫是死逻辑

```435:436:splitter.py
        if not self.status.cget('text').startswith('Processing'):
            self.status.config(text=lang['status_ready'])
```

状态栏文本从来不会是 `Processing`（运行时显示的是 `"1000/5000"`）。因此在**任务运行中切换语言，会把进度文本重置为"准备就绪"**，直到下一条 progress 消息到达才恢复。应基于 `self.state` 判断，并按状态重新渲染文本。

---

## 3. 性能分析

| 编号 | 位置 | 问题 | 影响 | 建议 |
|---|---|---|---|---|
| PERF-1 | 322 | 全量载入内存 | 大文件 OOM | CSV 用 `chunksize` 流式；Excel 用 `read_only=True` 迭代 |
| PERF-2 | 331-332 | `df.iloc[start:stop]` 每块产生拷贝 | 内存峰值 ≈ 原表 + 单块 | 流式读取后天然消除 |
| PERF-3 | 340-348 | 字符串反射 `getattr(pd.DataFrame, ...)` + 每次迭代判断 `export_format in [...]` | 每块一次字符串比较与属性查找（微） | 提前绑定可调用对象（见 2-6） |
| PERF-4 | 331 + 350 | 每个分块一条队列消息；`chunk_size=1` 时可产生百万级消息 | UI 线程在 `check_queue` 中长时间处理队列 → 假死 | 对进度做节流（如进度变化 ≥1% 或距上次 ≥100ms 才投递） |
| PERF-5 | 398 | 空闲时仍以 100ms 节拍永久轮询 | 常驻 CPU 唤醒（低但无意义） | 仅在 `state == RUNNING` 时 `after` 续期 |
| PERF-6 | 379-398 | `check_queue` 中若抛出 `queue.Empty` 以外的异常，末尾的 `after` **不会执行**，轮询永久停止 | 进度条"卡死"且无任何提示 | `try/finally` 保证续期；异常另行记录 |
| PERF-7 | 140-141 | `DwmGetColorizationColor` 等 COM/DWM 调用在启动路径上 | 启动略有延迟，且可能阻塞 | 移出主线程或懒执行（不关键） |
| PERF-8 | — | 无"分块数量/预估耗时"提示 | 用户误设 `chunk_size=1` 时无法预期 | 参数变化时实时计算 `ceil(total/chunk_size)` 并展示 |

---

## 4. 安全性分析

总体攻击面很小（本地单机桌面工具，无网络、无提权、无外部输入解析之外的暴露面），但仍存在值得处理的问题：

| 编号 | 风险 | 说明与建议 |
|---|---|---|
| SEC-1 | **CSV/Excel 公式注入**（中） | 分割表格时，若单元格内容以 `=`、`+`、`-`、`@`、Tab、CR 开头（如 `=cmd\|'/C calc'!A0`、`=HYPERLINK(...)`），导出为 CSV/XLSX 后用户用 Excel 打开会**触发公式求值**，可导致数据外泄或命令执行。建议提供"转义公式前缀"选项（默认对导出到 csv/xlsx 的对象列加前导 `'`）或在文档中明确风险。 |
| SEC-2 | **解压炸弹 / 超大文件**（中） | `pd.read_excel` 通过 openpyxl 解压 xlsx，恶意文件可在几 KB 内展开为 GB 级数据导致内存耗尽。建议读取前校验文件大小并检查 zip 解压比（`zipfile` 遍历 `file_size` 总和）。 |
| SEC-3 | **静默覆盖已有文件**（中） | 无覆盖确认、无备份、无序号递增，可能覆盖用户既有数据文件；若输出目录等于输入目录且用户手工修改格式，存在覆盖源文件的理论可能。建议预检冲突 + 原子写入 + 失败清理（见 P1-6）。 |
| SEC-4 | **裸 `except:`**（低） | 第 143 行 `except:` 吞掉所有异常（含 `KeyboardInterrupt`/`SystemExit`），既掩盖故障也无法审计。改为 `except Exception as e: logging.debug(...)`。 |
| SEC-5 | **宽泛 `except Exception` 泄露内部信息**（低） | 第 311-312 行把原始异常字符串直接展示给用户（如 `str(e)` 可能含本机完整路径、库内部实现细节）。建议对用户显示 i18n 文案，完整堆栈写入日志文件。 |
| SEC-6 | **拖放路径解析**（低） | `handle_drop` 对 `event.data` 未做路径合法性校验（是否目录、是否符号链接、扩展名是否受支持），仅依赖 `os.path.isfile`。建议复用 `_apply_input_file()` 做统一校验与白名单检查。 |
| SEC-7 | **依赖未固定上界**（低） | `requirements.txt` 使用 `>=` 无上界，而本报告 P0-2 正说明 pandas 大版本变更会**静默破坏功能**。建议改为兼容区间（如 `pandas>=2.0.3,<3.0`）或用 lock 文件/`uv`/`pip-tools` 固化。 |
| SEC-8 | **AGPL-3.0 许可**（提示） | AGPL 对"通过网络提供交互式服务"有强 copyleft 要求。作为桌面分发工具通常无碍，但若未来加入联网/服务化形态，需重新评估合规义务。属提示性说明，非缺陷。 |

---

## 5. 可读性与可维护性

### 5-1 单文件承担 5 种职责

`splitter.py` 同时包含：i18n 词典、格式注册表、死代码、业务逻辑、Tk UI 构建、事件循环。任何一处修改都需在 518 行中定位，认知负担高，且**业务逻辑无法脱离 GUI 测试**。

### 5-2 错误串语言混乱（与 README "完整错误信息本地化"承诺矛盾）

```366:372:splitter.py
        if chunk_size <= 0:
            errors.append("Chunk size must be positive")
        if not num_format.isdigit():
            errors.append(LANGUAGES[self.current_lang]['errors']['invalid_number'])
        if not output_dir:
            errors.append("Output directory required")
        if export_format not in EXPORT_FORMATS:
            errors.append("Invalid export format")
```

同一个函数里，一半走 i18n、一半硬编码英文。中文用户会看到中英混排的错误列表。

### 5-3 `validate_input` 职责混合（校验 + 提示 + 副作用）

它既返回 `bool`，又在内部调用 `self.show_error()` 产生 UI 副作用，导致：无法在测试中调用（会弹窗）、无法在批量场景复用、调用方需要记得检查返回值。建议改为**纯函数返回错误列表**/抛 `AppError`，由 UI 层统一渲染：

```python
def collect_errors(job: SplitJob) -> list[str]:     # 纯函数，可单测
    ...
```

### 5-4 `writer` 分支中的 `engine` 特判是冗余逻辑

```340:348:splitter.py
                if export_format in ['xlsx', 'xls'] and 'engine' in options:
                    try:
                        writer(chunk, output_path, **options)
                    except ModuleNotFoundError as e:
                        raise RuntimeError(...)
                else:
                    writer(chunk, output_path, **options)
```

两个分支的 `writer(...)` 调用**完全相同**，唯一区别是是否包一层 `ModuleNotFoundError` 转换。这段结构完全可以直接简化为"统一 try/except"，且：
- `e.name` 可能为 `None` → 会输出 `Missing dependency: None`；
- 只对 xlsx/xls 做依赖转换，其他格式缺失依赖（如未来加 `read_html` 需要 `lxml`）无保护；
- 应在**启动时**做一次依赖自检（`importlib.util.find_spec`），而不是等用户跑到一半才失败。

### 5-5 魔法数与硬编码

`"700x450"`（152 行）、`1000`（182 行）、`"001"`（189 行）、`after(100, ...)`（398 行）、`+10`（456 行）、`foreground="yellow"`（468 行）、`0x80`（142 行）散落各处。建议集中到 `constants.py` 或 `dataclass Settings`。

### 5-6 命名与接口

- `get_splitter` 返回策略函数但返回类型无标注，且已确认是死代码。
- `num_format` 名为"格式"实为"位数"，`chunk_size` 与 `size_entry`/`size_label` 命名不一致（同一概念三种叫法）。
- `toggle_operation` 名为 toggle 但内含具体分支逻辑，建议 `on_primary_button()`。
- 无类型注解、无 `mypy`/`pyright` 配置，重构时缺乏编译器级保护。

### 5-7 缺少"运行结果摘要"

任务结束后只有"分割完成"三字。建议输出：`已生成 5 个文件 → D:\out（耗时 1.8s）`，并提供"打开输出目录"按钮（`os.startfile`），显著提升可用性。

---

## 6. 错误处理改进建议

1. **建立异常分类体系**，用 i18n key 承载面向用户的文案，插件/库异常一律包裹：

```python
class AppError(Exception):
    """携带 i18n key 的业务异常，UI 层负责本地化渲染。"""
    def __init__(self, key: str, **ctx):
        super().__init__(key)
        self.key, self.ctx = key, ctx

class FileFormatError(AppError): ...
class DependencyMissingError(AppError): ...
class CancelledByUser(Exception): ...
```

2. **引入日志**（当前 `logging` 已导入却未使用）：

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
```

在 `worker_task` 顶层 `except Exception: logging.exception("split failed")`，用户只看到友好文案 + "详情见日志"。日志路径：`%LOCALAPPDATA%/UniversalTableSplitter/logs/`。

3. **拒绝裸 `except` / 无信息的宽泛捕获**：所有 `except Exception` 必须 `logging.exception`；`except:` 改为具体异常类型。

4. **失败原子化**：临时文件 + `os.replace`，失败清理（见 P1-6）。

5. **启动依赖自检**：`openpyxl`（xlsx 写）、`xlrd`（xls 读）、`tkinterdnd2`（可选拖放）在启动时探测，缺失时在 UI 上以不可用状态呈现，而非运行中途报错。

6. **统一的"错误展示组件"**：状态栏不承载多行错误。长时间错误用 `messagebox.showerror`（可滚动详情）或自绘错误面板；状态栏仅显示一句话摘要。

7. **关闭窗口时优雅退出**：绑定 `WM_DELETE_WINDOW` → 若在运行则提示确认并设置取消令牌，`join(timeout)` 后再销毁，避免留下半写文件。

---

## 7. 测试覆盖方案（当前为 0）

### 7-1 前置条件：把核心逻辑从 UI 中剥离

只要 `root` 还在模块级创建，就**无法**写任何单元测试。重构后目录建议：

```
universal_table_splitter/
├── __init__.py            # __version__ 单一来源
├── core/
│   ├── plan.py            # plan_chunks / format_suffix / build_output_path  (纯函数)
│   ├── readers.py         # 编码回退 / 流式读取 / sheet 选择
│   ├── writers.py         # ExportSpec 注册表 / 原子写入 / 公式转义
│   ├── errors.py          # AppError 体系
│   └── job.py             # SplitJob(dataclass) / SplitResult
├── i18n.py                # LANGUAGES + tr(key, lang)
├── ui/
│   ├── app.py             # UniversalSplitterApp
│   ├── widgets.py         # FileSelector
│   └── theme.py           # detect_dark_mode / enable_dpi_awareness
├── config.py              # 常量与默认值
└── __main__.py            # entrypoint: python -m universal_table_splitter
```

### 7-2 必测用例清单（pytest + `tmp_path`）

```python
# tests/test_plan.py  —— 纯逻辑，无需 GUI
import pytest
from universal_table_splitter.core.plan import plan_chunks, format_suffix

@pytest.mark.parametrize("total,size,expected", [
    (2500, 1000, [(0, 1000), (1000, 2000), (2000, 2500)]),  # 末块不越界
    (2000, 1000, [(0, 1000), (1000, 2000)]),                # 整除
    (10,   1000, [(0, 10)]),                                # 单块
    (0,    1000, []),                                       # 空表
])
def test_plan_chunks(total, size, expected):
    assert plan_chunks(total, size) == expected

@pytest.mark.parametrize("size", [0, -1])
def test_plan_chunks_rejects_non_positive(size):
    with pytest.raises(ValueError):
        plan_chunks(100, size)

def test_format_suffix_pads_and_grows():
    assert format_suffix(1, 3) == "001"
    assert format_suffix(999, 3) == "999"
    assert format_suffix(1000, 3) == "1000"      # 溢出自然增宽，不报错
```

关键功能测试（当前缺陷的回归护栏）：

| 测试 | 断言 | 防护的缺陷 |
|---|---|---|
| `test_no_xls_export` | `"xls" not in EXPORT_FORMATS` | P0-2 |
| `test_csv_output_has_bom_utf8` | 输出文件前 3 字节为 `b'\xef\xbb\xbf'`，且 pandas 读回内容与源一致 | P1-1 |
| `test_reads_gbk_csv` | 用 `gb18030` 写入的固定样例能被正确读回 | P1-2 |
| `test_fidelity_preserves_leading_zeros` | `"00123"` 读回后仍为 `"00123"` | P1-3 |
| `test_multi_sheet_selects_sheet` | 双 sheet 文件按指定 sheet 输出 | P1-4 |
| `test_no_partial_file_on_failure` | 写第 2 块时 mock 抛异常 → 输出目录内无残留文件 | P1-6 |
| `test_num_format_length_bound` | `"000000000000"` 被拒绝 | P1-7 |
| `test_dnd_parses_spaced_path` | `splitlist("{C:/a b/c.csv}")` → 单一路径 | P0-3 |
| `test_cancel_stops_worker` | 取消后写入文件数 < 总块数，且线程已退出 | P0-1 |
| `test_unicode_roundtrip` | 中文表头/内容 split → merge 后完全一致 | 通用保真 |

GUI 冒烟测试（可用 `pytest-xvfb`/Windows 上直接跑）：

```python
def test_ui_builds_and_switches_language():
    app = UniversalSplitterApp(...)
    try:
        assert app.lang_btn.cget("text") == LANGUAGES["cn"]["lang_btn"]
        app.toggle_language()
        assert app.lang_btn.cget("text") == LANGUAGES["en"]["lang_btn"]   # 防 widget 查找回归
    finally:
        app.root.destroy()
```

### 7-3 质量门禁

- `ruff`（含 `E722` 裸 except、`F401` 未使用导入 → 直接命中本报告 2-2 与 4-SEC-4）
- `black` 统一格式；`mypy --strict`（对 `core/` 至少 `--disallow-untyped-defs`）
- `pytest --cov=universal_table_splitter --cov-fail-under=80`
- GitHub Actions matrix：`windows-latest / ubuntu-latest / macos-latest` × Python `3.9–3.12`
- `pre-commit` 钩子保证本地提交即通过

---

## 8. 文档与工程化问题

### 8-1 README 与实现的三处直接矛盾（应优先修正）

| README | 行号 | 实现事实 |
|---|---|---|
| 输入支持 `HTML` | 9 | `SUPPORTED_EXTS` 无 `.html`，拖放 HTML 会提示"不支持的格式" |
| 行数范围 `1-10000` | 10, 45 | 仅校验 `> 0`，无上界 |
| 编号格式"使用 Python 格式字符串（如 `03d`）" | 46 | `isdigit()` 校验会**拒绝** `03d` |

### 8-2 README 其他待补

- 未说明 `tkinterdnd2` 是可选的拖放依赖（只在应用内弹窗提一次），应先给安装指引再描述功能；
- `pywin32` 应标注仅 Windows 需要（见 8-4）；
- 打包命令把本机绝对路径 `C:\Python\Lib\site-packages\ttkbootstrap` 写死在文档里（第 38 行），对其他用户不可用；应改为提交 `universal_table_splitter.spec` 文件（`.gitignore` 里已有 `...spec` 条目，说明作者本地用过）；
- 缺少：架构说明、支持的 Python 版本、格式/编码行为说明（尤其是"仅第一个 sheet""按文本保真的建议"）、限制与已知问题、截图、变更日志链接、"如何运行测试"。

### 8-3 `requirements.txt` 问题

```
pandas>=2.0.3
ttkbootstrap>=1.10.0
openpyxl>=3.1.2
xlrd>=2.0.1
pywin32>=306
python-dotenv>=1.0.0  # 可选，如需环境变量支持
```

- `python-dotenv`：**代码中零引用**，应删除（`F401` 等价物：无用依赖）；
- `pywin32`：仅 Windows 且仅主题探测需要 → 加环境标记 `pywin32>=306; sys_platform == "win32"`；
- `tkinterdnd2`：代码里是可选导入的能力，却未在依赖中列出 → 应作为 `[project.optional-dependencies].dnd`；
- `html5lib`/`xlsxwriter`：README 第 59 行让用户装这两个包，但它们**并非代码所需**（实测 `to_html` 无需额外依赖，`to_excel` 用 `openpyxl`）→ 文档误导，应删除；
- 全部依赖无上界 → 见 SEC-7。

### 8-4 缺少打包与项目元数据

建议新增 `pyproject.toml`：

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "universal-table-splitter"
version = "1.0.0"
description = "跨平台 GUI 表格分割工具，支持 CSV/Excel/JSON/TSV 流式分块导出"
readme = "README.md"
requires-python = ">=3.9"
license = { file = "LICENSE" }
dependencies = [
    "pandas>=2.0.3,<3.0",
    "ttkbootstrap>=1.10,<2",
    "openpyxl>=3.1.2,<4",
    "xlrd>=2.0.1,<3",
    "pywin32>=306; sys_platform == 'win32'",
]

[project.optional-dependencies]
dnd = ["tkinterdnd2>=0.3"]
dev = ["pytest>=8", "pytest-cov", "ruff", "black", "mypy", "pre-commit", "pyinstaller"]

[project.gui-scripts]
table-splitter = "universal_table_splitter.__main__:main"

[tool.ruff]
line-length = 100
select = ["E", "F", "W", "I", "UP", "B", "SIM", "C4", "PTH"]

[tool.mypy]
python_version = "3.9"
warn_unused_ignores = true
disallow_untyped_defs = true
```

> 提示：一旦引入 `pyproject.toml` 与 `__main__.py`，`requirements.txt` 可精简为 `-e .[dev]` 或直接删除，避免双份依赖来源。

### 8-5 建议新增文件

`CHANGELOG.md`（Keep a Changelog 格式）、`.github/workflows/ci.yml`、`.github/ISSUE_TEMPLATE/bug_report.yml`、`tests/`、`CONTRIBUTING.md`。当前 `.gitignore` 只覆盖 PyInstaller 产物，**缺少** `__pycache__/`、`*.pyc`、`.venv/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`dist/`（通配）等标准条目。

---

## 9. 架构改进建议（目标形态）

改造前：`UI ⟷ 业务 ⟷ 配置 ⟷ i18n` 全部挤在一个类里，线程通过 `self.running` 布尔量非法共享状态。

改造后建议的分层：

```
┌──────────────────────────────────────────────┐
│ ui/app.py                                    │
│  - Tk 事件、控件状态、进度渲染、i18n 切换      │
│  - 只通过 queue 接收 worker 消息（单向）       │
└───────────────┬──────────────────────────────┘
                │  SplitJob (frozen dataclass, 不可变)
                │  CancelToken (threading.Event)
                ▼
┌──────────────────────────────────────────────┐
│ core/job.py  run_split(job, cancel, on_progress) │
│  - 纯业务：计划分块 → 读取 → 写入 → 汇总       │
│  - 不 import tkinter，可被 CLI/批处理复用      │
└───────┬──────────────────────┬───────────────┘
        ▼                      ▼
   core/readers.py        core/writers.py
   (编码回退/流式/多sheet)  (ExportSpec/原子写入/公式转义)
```

关键收益：

1. **可测试**：`run_split` 是纯函数式接口（输入 job + 回调），可直接在测试中调用并断言输出文件，无需 GUI。
2. **可复用**：同一套核心可挂 CLI（`table-splitter in.csv --rows 1000 --format xlsx`），大幅提升工具性与自动化能力。
3. **可扩展**：新增输入/输出格式只需在注册表加一项；`ExportSpec` 用可调用对象替代字符串反射，重构安全。
4. **可取消**：`CancelToken` 贯穿读取与写入的每个块边界，取消语义明确、无重入风险。
5. **可观测**：`on_progress(ChunkProgress)` 回调，UI 与 CLI 各自渲染（UI 走队列 + 节流，CLI 走 tqdm）。

`SplitJob` 建议签名：

```python
@dataclass(frozen=True)
class SplitJob:
    input_path: Path
    output_dir: Path
    chunk_size: int
    digits: int                      # 由 num_format 归一化为"位数"
    export_format: str
    sheet_name: str | int = 0
    fidelity_mode: bool = True       # 按文本读取，保持前导零等
    escape_formulas: bool = False

@dataclass(frozen=True)
class SplitResult:
    files: tuple[Path, ...]
    rows: int
    elapsed_s: float
    canceled: bool = False
```

---

## 10. 优先改进路线图

### 阶段一：缺陷修复（0.5 天，最高性价比）

1. 修复取消机制：`threading.Event` 协作取消 + 禁止并发重入（**P0-1，数据损坏风险**）
2. 移除不可用的 `.xls` 导出（**P0-2，功能必错**）
3. 拖放路径改用 `root.tk.splitlist()`，并抽取 `_apply_input_file()` 消除重复（**P0-3**）
4. CSV/TSV 导出加 `encoding='utf-8-sig'`；CSV/TSV 读取加编码回退（**P1-1、P1-2**）
5. 编号格式：`zfill` 语义显式化 + `1..10` 位长度上界；修正 README 的 `03d` 描述（**P1-7**）
6. 修掉重复校验、修掉 `int()` 异常直出、错误串全部走 i18n（**P2-1、P2-2、5-2**）
7. 进度不越界；完成后保留 100%；空表显式提示（**P2-5、P2-6**）
8. 删除死代码与未使用导入（**2-1、2-2**）
9. 裸 `except:` → 具体异常 + 日志（**4-SEC-4**）

### 阶段二：结构与健壮性（1–2 天）

10. 拆分模块：`core/`（纯逻辑）+ `ui/` + `i18n.py` + `config.py`；`root` 移入 `main()`（**2-3、5-1**）
11. `AppError` 异常体系 + 日志（RotatingFileHandler）+ 启动依赖自检（**§6**）
12. 原子写入（临时文件 + `os.replace`）+ 失败清理 + 覆盖冲突确认（**P1-6、SEC-3**）
13. CSV/TSV 流式读取（`chunksize`），消除大文件 OOM；Excel 加文件大小与解压比预检（**P1-5、SEC-2**）
14. 保真模式（`dtype=str, keep_default_na=False`）作为默认或选项（**P1-3**）
15. 多 sheet 选择与提示（**P1-4**）
16. `ExportSpec` 注册表替代字符串反射；`MappingProxyType` 防误改（**2-6**）
17. 控件引用化 + `AppState` 状态机 + widget 查找去脆弱化（**2-7、2-8**）
18. 主题探测改用注册表 + macOS 支持；DPI 感知提到 `main()` 最前（**2-4、2-5**）
19. 队列进度节流 + `after` 续期用 `finally` 保证（**PERF-4、PERF-6**）

### 阶段三：测试与工程化（1 天）

20. `pyproject.toml` + `__main__.py` + `__version__` 单一来源；`requirements.txt` 清理（**8-3、8-4**）
21. pytest 用例（§7-2 清单）+ `pytest-cov` 阈值 80%
22. `ruff`/`black`/`mypy` + `pre-commit` + GitHub Actions 三平台矩阵
23. PyInstaller `.spec` 文件入仓，修正 README 打包说明（**8-2**）
24. README 修正三处矛盾 + 补架构/限制/测试说明；新增 `CHANGELOG.md`、`CONTRIBUTING.md`；补全 `.gitignore`（**8-1、8-5**）
25. 公式注入转义选项（**SEC-1**）；结果摘要 + "打开输出目录"按钮（**5-7**）

### 阶段四：体验增强（可选）

26. 记住上次参数/目录（`%APPDATA%` 配置持久化）
27. 预检估算：显示"将生成 N 个文件、预计占用 X MB"，超阈值前确认
28. CLI 子命令复用 `core`，支持批处理与自动化
29. 结果摘要导出为 `split_report.log`，便于团队复核

---

## 11. 附：关键结论速览

**必须立刻修（否则用户必然踩坑或数据受损）**

- 取消 = 假取消，且会启动第二个线程并发写同一批文件 → **输出文件可能损坏**
- `.xls` 导出在 pandas ≥ 2.0 下**必然失败**（实测 `ValueError: No engine for filetype: 'xls'`）
- 拖放含空格路径**静默失效**（`event.data.split()`）
- 中文 CSV 导出无 BOM → Excel 乱码；GBK 输入 CSV → 直接读取失败

**严重影响专业性**

- 零测试、零日志、零 CI、零类型检查
- 核心逻辑与 Tk 强耦合，模块级创建窗口导致不可测试
- README 与实现 3 处矛盾（HTML 输入、行数上界、`03d` 格式）

**建议的中期投资**

- `core/` 与 `ui/` 分层 + `SplitJob`(frozen dataclass) + `CancelToken` + `AppError`
- 流式读取解决大文件；原子写入解决残留与覆盖
- 注册表 + 可调用对象替代字符串反射，让新增格式变成"加一行"
