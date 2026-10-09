"""后台工作线程。

核心层（``core.job``）是同步阻塞的：``preflight`` 要打开文件统计行数，
``run_split`` 要逐块读写成百上千个文件。这些都不能放在界面线程里，
否则窗口会直接卡死。

Qt 的规矩只有一条：**子线程绝不碰控件**。所有结果都通过 ``Signal`` 发回主线程，
Qt 会自动把信号排队到接收者所在的线程（默认是主线程），这就是线程安全的边界。

拆成两个 worker 而不是一个，是因为中间夹着"要不要继续"的询问：
``preflight`` 完成后需要根据文件数量和覆盖冲突弹窗问用户，
弹窗必须发生在主线程，所以流程天然分成两段。
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from ..core.job import SplitJob, preflight, run_split
from ..errors import AppError, CanceledByUser
from ..logging_setup import log_file_path

logger = logging.getLogger(__name__)


def as_app_error(exc: BaseException) -> AppError:
    """把任意异常翻译成 ``AppError``，保证界面永远拿得到可渲染的文案。

    未知异常不吞掉：完整堆栈进日志文件，用户看到的是"出错了，日志在这里"。
    """
    logger.exception("unexpected error in worker: %s", exc)
    return AppError("err.unexpected", path=log_file_path())


class PreflightWorker(QThread):
    """预检线程：打开数据源、统计行数、算出输出文件数与覆盖冲突。

    成功后发出的 ``Preflight`` 对象**持有已打开的文件句柄**，
    接收方必须二选一：交给 ``SplitWorker`` 复用，或者调用 ``close()`` 释放。
    忘了关会泄漏文件句柄——Windows 上表现为"输出文件被占用，删不掉"。
    """

    #: 预检成功，携带 Preflight
    ready = Signal(object)
    #: 预检失败，携带 AppError
    failed = Signal(object)
    #: 用户在预检阶段就点了取消。带一个 object 参数（恒为 None），
    #: 好让界面把"取消"统一交给同一个处理函数，不必写两个签名不同的槽。
    canceled = Signal(object)

    def __init__(self, job: SplitJob, cancel: threading.Event, parent=None) -> None:
        super().__init__(parent)
        self._job = job
        self._cancel = cancel

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            report = preflight(self._job, cancel=self._cancel)
        except CanceledByUser:
            self.canceled.emit(None)
        except AppError as exc:
            self.failed.emit(exc)
        except BaseException as exc:  # noqa: BLE001 - 线程里必须兜住一切
            self.failed.emit(as_app_error(exc))
        else:
            self.ready.emit(report)


class SplitWorker(QThread):
    """执行线程：把任务交给 ``run_split``，进度用信号回传。

    取消是协作式的：``cancel_event`` 只在分块边界被检查，因此取消后
    不会留下半写的文件（写入本身是原子的）。
    """

    #: 进度更新，携带 ProgressEvent
    progress = Signal(object)
    #: 正常完成，携带 SplitResult
    succeeded = Signal(object)
    #: 失败，携带 AppError
    failed = Signal(object)
    #: 用户取消，携带已完成的部分结果（可能为 None）
    canceled = Signal(object)

    def __init__(
        self,
        job: SplitJob,
        cancel: threading.Event,
        source=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._job = job
        self._cancel = cancel
        self._source = source

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            result = run_split(
                self._job,
                on_progress=self.progress.emit,
                cancel=self._cancel,
                source=self._source,
            )
        except CanceledByUser as exc:
            self.canceled.emit(exc.partial)
        except AppError as exc:
            self.failed.emit(exc)
        except BaseException as exc:  # noqa: BLE001 - 线程里必须兜住一切
            self.failed.emit(as_app_error(exc))
        else:
            self.succeeded.emit(result)
        finally:
            # run_split 会关闭传进去的 source；这里清掉引用，
            # 避免 worker 对象被界面持有期间一直拖着已关闭的数据源
            self._source = None
