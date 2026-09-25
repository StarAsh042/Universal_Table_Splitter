"""全局常量与默认配置。

所有可调参数集中在此，避免"魔法数"散落在 UI、核心与 CLI 各处。
"""

from __future__ import annotations

APP_NAME = "Universal Table Splitter"
APP_NAME_CN = "通用表格分割器"
APP_SLUG = "universal_table_splitter"
GITHUB_URL = "https://github.com/StarAsh042"
AUTHOR = "StarAsh042"

DEFAULT_LANG = "cn"
DEFAULT_CHUNK_SIZE = 1_000
DEFAULT_NUM_FORMAT = "001"
DEFAULT_EXPORT_FORMAT = "csv"

MIN_CHUNK_SIZE = 1
MAX_CHUNK_SIZE = 1_000_000

MIN_NUM_DIGITS = 1
MAX_NUM_DIGITS = 10

#: 预估输出文件数超过该值时，启动前必须让用户确认，避免误参数产生海量文件
LARGE_JOB_FILE_THRESHOLD = 1_000

#: 小于该体积的 CSV/TSV 走一次性载入（更快），超过则走流式分块（内存有界）
STREAM_READ_THRESHOLD_BYTES = 64 * 1024 * 1024

#: 必须完整载入内存的格式（JSON / XLS）的体积上限
MAX_FULL_LOAD_BYTES = 512 * 1024 * 1024

#: xlsx（zip 容器）解压比上限，用于防御解压炸弹
MAX_INFLATE_RATIO = 200

#: UI 进度刷新节流间隔（秒）
PROGRESS_MIN_INTERVAL_S = 0.08

#: UI 队列轮询间隔（毫秒）
QUEUE_POLL_MS = 60

#: 等待用户确认的超时（秒），超时视为中止任务
CONFIRM_TIMEOUT_S = 300.0

WINDOW_GEOMETRY = "820x600"
WINDOW_MIN_WIDTH = 660
WINDOW_MIN_HEIGHT = 520

#: 保留的"编号格式"输入框宽度
FORMAT_ENTRY_WIDTH = 8
SIZE_ENTRY_WIDTH = 10

#: 单次 CSV 分块读取时，判断取消的检查间隔（行）
CANCEL_CHECK_INTERVAL = 50_000
