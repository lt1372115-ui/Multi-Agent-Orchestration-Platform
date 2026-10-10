"""对话会话基础设施：会话 id 生成与会话级锁。

流式与非流式对话共用，独立成模块避免 ``service`` 与 ``stream`` 相互依赖。
"""

import asyncio
import uuid
from weakref import WeakValueDictionary

# 会话级锁表：用弱引用字典，会话结束后锁对象可被回收，避免长跑进程按「访问过的
# 会话数」无界增长（锁在 ``async with`` 期间由调用方强引用持有，不会被提前回收）。
_thread_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def new_conversation_id() -> str:
    """生成全局唯一的会话 id，作为短期记忆的 ``thread_id``。"""
    return uuid.uuid4().hex


def thread_lock(thread_id: str) -> asyncio.Lock:
    """获取会话级锁，串行化同一会话的并发写入，避免 checkpoint 读改写竞态。"""
    lock = _thread_locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _thread_locks[thread_id] = lock
    return lock
