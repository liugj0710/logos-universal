"""
Browser Pool — 单浏览器进程 + 多标签页并发复用 (TabPool)

v0.2.5 修复：
- _ensure_browser 拆分为 sync + async 双版本，_new_tab（sync）调用 sync 版本
- _cleanup_tab / _destroy_tab / browser.states.is_alive 全部加 asyncio.wait_for 超时
- _cleanup_tab 移出锁外执行，彻底消除死锁
- 浏览器健康检查超时 3 秒，避免 is_alive 本身 hang 住
"""

import os
import time
import asyncio
import subprocess
from typing import Optional, List

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    DP_AVAILABLE = True
except ImportError:
    ChromiumPage = None
    ChromiumOptions = None
    DP_AVAILABLE = False

_POOL_DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", ".browser_pool_data")
os.makedirs(_POOL_DATA_ROOT, exist_ok=True)

MAX_TAB_USE_COUNT = 50
TAB_CLEANUP_TIMEOUT = 5.0
BROWSER_HEALTH_TIMEOUT = 3.0


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def _kill_port_process(port: int):
    """查找并杀掉占用指定端口的进程（Windows）"""
    try:
        result = subprocess.run(
            f'netstat -ano | findstr :{port}',
            shell=True, capture_output=True, text=True, encoding='gbk', errors='ignore'
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    subprocess.run(f'taskkill /F /PID {pid}', shell=True, capture_output=True)
                    print(f"[TabPool] 已杀掉端口 {port} 的进程 PID {pid}")
                    break
    except Exception:
        pass


class _PoolContext:
    def __init__(self, pool, semaphore):
        self.pool = pool
        self.semaphore = semaphore
        self.tab = None

    async def __aenter__(self):
        await self.semaphore.acquire()
        self.tab = await self.pool._checkout()
        return self.tab

    async def __aexit__(self, exc_type, exc, tb):
        # 移出锁外执行 cleanup，避免 cleanup hang 住导致死锁
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self.pool._cleanup_tab, self.tab),
                timeout=TAB_CLEANUP_TIMEOUT
            )
        except asyncio.TimeoutError:
            print(f"[TabPool:{self.pool.name} {_ts()}] 清理标签页超时，强制销毁")
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.pool._destroy_tab, self.tab),
                    timeout=TAB_CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                print(f"[TabPool:{self.pool.name} {_ts()}] 销毁标签页也超时，放弃")
        except Exception as e:
            print(f"[TabPool:{self.pool.name} {_ts()}] 清理标签页异常: {e}")

        await self.pool._checkin(self.tab)
        self.semaphore.release()


class TabPool:
    def __init__(self, name: str, pool_size: int = 3, base_port: int = 9223):
        self.name = name
        self.pool_size = pool_size
        self.base_port = base_port
        self._tabs: List = []
        self._tab_counts: dict = {}
        self._semaphore = asyncio.Semaphore(pool_size)
        self._lock = asyncio.Lock()
        self._closed = False
        self._browser = None
        self._initialized = False

    def _create_browser(self):
        """同步创建浏览器进程：清旧进程 → ChromiumPage 启动 → 取 browser 对象"""
        if not DP_AVAILABLE:
            return None

        _kill_port_process(self.base_port)
        time.sleep(0.5)

        data_dir = os.path.join(_POOL_DATA_ROOT, f"{self.name}_browser")
        os.makedirs(data_dir, exist_ok=True)

        co = ChromiumOptions()
        co.headless(True)
        co.set_argument("--remote-debugging-port", str(self.base_port))
        co.set_argument("--user-data-dir", data_dir)
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument("--disable-gpu")
        co.set_argument("--no-first-run")
        co.set_argument("--no-default-browser-check")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--disable-infobars")
        co.set_argument("--window-size", "1920,1080")
        co.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0'
        )

        try:
            print(f"[TabPool:{self.name} {_ts()}] 启动浏览器 (端口 {self.base_port})")
            page = ChromiumPage(co)
            browser = page.browser
            time.sleep(0.5)
            print(f"[TabPool:{self.name} {_ts()}] 浏览器启动成功")
            return browser
        except Exception as e:
            print(f"[TabPool:{self.name} {_ts()}] 浏览器启动失败: {e}")
            return None

    def _browser_is_alive_sync(self):
        """同步版本：浏览器健康检查"""
        try:
            if self._browser is None:
                return False
            return self._browser.states.is_alive
        except Exception:
            return False

    def _ensure_browser_sync(self):
        """同步版本：确保 browser 健康，供 _new_tab 等 sync 函数调用"""
        if self._browser is None:
            self._browser = self._create_browser()
            return
        try:
            if not self._browser.states.is_alive:
                print(f"[TabPool:{self.name} {_ts()}] browser 不健康，重建...")
                try:
                    self._browser.quit()
                except Exception:
                    pass
                self._browser = self._create_browser()
        except Exception:
            self._browser = self._create_browser()

    async def _ensure_browser(self):
        """async 版本：带超时保护，供 async 上下文调用"""
        if self._browser is None:
            self._browser = await asyncio.to_thread(self._create_browser)
            return

        try:
            is_alive = await asyncio.wait_for(
                asyncio.to_thread(self._browser_is_alive_sync),
                timeout=BROWSER_HEALTH_TIMEOUT
            )
            if not is_alive:
                print(f"[TabPool:{self.name} {_ts()}] browser 不健康，重建...")
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._browser.quit),
                        timeout=TAB_CLEANUP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    print(f"[TabPool:{self.name} {_ts()}] 关闭旧浏览器超时，强制 kill")
                    _kill_port_process(self.base_port)
                except Exception:
                    pass
                self._browser = await asyncio.to_thread(self._create_browser)
        except asyncio.TimeoutError:
            print(f"[TabPool:{self.name} {_ts()}] browser 健康检查超时，强制重建")
            _kill_port_process(self.base_port)
            self._browser = await asyncio.to_thread(self._create_browser)
        except Exception:
            self._browser = await asyncio.to_thread(self._create_browser)

    def _new_tab(self):
        """同步创建新标签页并预热（供 asyncio.to_thread 调用）"""
        self._ensure_browser_sync()
        if self._browser is None:
            print(f"[TabPool:{self.name} {_ts()}] 浏览器未创建，无法新建标签页")
            return None
        try:
            tab = self._browser.new_tab()
            tab.get("about:blank")
            time.sleep(0.3)
            return tab
        except Exception as e:
            print(f"[TabPool:{self.name} {_ts()}] 创建标签页失败: {e}")
            return None

    def _cleanup_tab(self, tab):
        """同步清理标签页（供 to_thread 调用）"""
        try:
            tab.run_cdp("Page.stopLoading")
            tab.get("about:blank")
        except Exception:
            pass

    def _destroy_tab(self, tab):
        """同步销毁标签页（供 to_thread 调用）"""
        try:
            tab.close()
        except Exception:
            pass

    async def _init(self):
        if self._initialized or self._closed:
            return

        async with self._lock:
            if self._initialized or self._closed:
                return

            print(f"[TabPool:{self.name} {_ts()}] 预创建 {self.pool_size} 个标签页...")
            for i in range(self.pool_size):
                tab = await asyncio.to_thread(self._new_tab)
                if tab:
                    self._tabs.append(tab)
                    self._tab_counts[id(tab)] = 0
                    print(f"[TabPool:{self.name} {_ts()}] 标签页 #{i} 创建成功")
                else:
                    print(f"[TabPool:{self.name} {_ts()}] 标签页 #{i} 创建失败")
                await asyncio.sleep(0.5)

            self._initialized = True
            print(f"[TabPool:{self.name} {_ts()}] 初始化完成，Pool 中 {len(self._tabs)}/{self.pool_size} 个标签页")

    async def _checkout(self):
        if not self._initialized:
            await self._init()

        async with self._lock:
            if self._closed:
                raise RuntimeError(f"TabPool '{self.name}' 已关闭")

            # 如果 browser 死了，清空所有标签页
            try:
                is_alive = await asyncio.wait_for(
                    asyncio.to_thread(self._browser_is_alive_sync),
                    timeout=BROWSER_HEALTH_TIMEOUT
                )
                if not is_alive:
                    for t in self._tabs:
                        self._tab_counts.pop(id(t), None)
                    self._tabs.clear()
            except asyncio.TimeoutError:
                print(f"[TabPool:{self.name} {_ts()}] checkout 健康检查超时，清空 Pool")
                for t in self._tabs:
                    self._tab_counts.pop(id(t), None)
                self._tabs.clear()
            except Exception:
                for t in self._tabs:
                    self._tab_counts.pop(id(t), None)
                self._tabs.clear()

            while self._tabs:
                tab = self._tabs.pop(0)
                count = self._tab_counts.get(id(tab), 0)

                if count < MAX_TAB_USE_COUNT:
                    print(f"[TabPool:{self.name} {_ts()}] checkout 标签页 (已用 {count} 次)，Pool 剩余 {len(self._tabs)}")
                    return tab
                else:
                    await asyncio.to_thread(self._destroy_tab, tab)
                    self._tab_counts.pop(id(tab), None)
                    print(f"[TabPool:{self.name} {_ts()}] 淘汰旧标签页 (已用 {count} 次)")

            # Pool 空，应急创建
            print(f"[TabPool:{self.name} {_ts()}] Pool 为空，应急创建标签页...")
            tab = await asyncio.to_thread(self._new_tab)
            if tab is None:
                raise RuntimeError(f"TabPool '{self.name}' 无法创建标签页")
            self._tab_counts[id(tab)] = 0
            return tab

    async def _checkin(self, tab):
        """checkin 只做计数和入队，cleanup 已在 __aexit__ 中完成"""
        async with self._lock:
            if self._closed:
                await asyncio.wait_for(
                    asyncio.to_thread(self._destroy_tab, tab),
                    timeout=TAB_CLEANUP_TIMEOUT
                )
                self._tab_counts.pop(id(tab), None)
                return

            # browser 死了，直接销毁
            try:
                is_alive = await asyncio.wait_for(
                    asyncio.to_thread(self._browser_is_alive_sync),
                    timeout=BROWSER_HEALTH_TIMEOUT
                )
                if not is_alive:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._destroy_tab, tab),
                        timeout=TAB_CLEANUP_TIMEOUT
                    )
                    self._tab_counts.pop(id(tab), None)
                    return
            except asyncio.TimeoutError:
                print(f"[TabPool:{self.name} {_ts()}] checkin 健康检查超时，销毁标签页")
                await asyncio.wait_for(
                    asyncio.to_thread(self._destroy_tab, tab),
                    timeout=TAB_CLEANUP_TIMEOUT
                )
                self._tab_counts.pop(id(tab), None)
                return
            except Exception:
                await asyncio.wait_for(
                    asyncio.to_thread(self._destroy_tab, tab),
                    timeout=TAB_CLEANUP_TIMEOUT
                )
                self._tab_counts.pop(id(tab), None)
                return

            count = self._tab_counts.get(id(tab), 0)
            self._tab_counts[id(tab)] = count + 1

            if len(self._tabs) < self.pool_size:
                self._tabs.append(tab)
                print(f"[TabPool:{self.name} {_ts()}] checkin 标签页 (累计 {count + 1} 次)，Pool 中 {len(self._tabs)}/{self.pool_size} 个")
            else:
                await asyncio.wait_for(
                    asyncio.to_thread(self._destroy_tab, tab),
                    timeout=TAB_CLEANUP_TIMEOUT
                )
                self._tab_counts.pop(id(tab), None)
                print(f"[TabPool:{self.name} {_ts()}] checkin 销毁标签页（Pool 已满）")

    def acquire(self):
        return _PoolContext(self, self._semaphore)

    def close_all(self):
        self._closed = True
        for tab in self._tabs:
            try:
                tab.close()
            except Exception:
                pass
        self._tabs.clear()
        self._tab_counts.clear()
        try:
            if self._browser:
                self._browser.quit()
        except Exception:
            pass
        self._browser = None
        print(f"[TabPool:{self.name} {_ts()}] 浏览器进程已关闭")
