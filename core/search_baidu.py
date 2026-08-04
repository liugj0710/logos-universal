"""
百度搜索爬虫 — Tab Pool 并发复用
v0.2.5 修复：确保 requests.Session 正确关闭
"""

import asyncio
import time
from typing import List, Dict, Any
from urllib.parse import quote

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from core.browser_pool import TabPool, DP_AVAILABLE

baidu_pool = TabPool("baidu", pool_size=5, base_port=9226)


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def close_baidu_browser():
    baidu_pool.close_all()


def _parse_baidu_results(html: str, top_k: int) -> List[Dict]:
    if not BeautifulSoup:
        return []

    soup = BeautifulSoup(html, "html.parser")
    raw_results = []
    containers = soup.select("#content_left .result") or soup.select(".c-container")

    print(f"[search_baidu {_ts()}] 解析到 {len(containers)} 个结果容器")

    for idx, container in enumerate(containers[:top_k]):
        h3 = container.select_one("h3")
        if not h3:
            continue

        a_tag = h3.select_one("a")
        if not a_tag:
            continue

        title = a_tag.get_text(strip=True)
        url = a_tag.get("href", "")

        abstract = (
            container.select_one(".content-right_8Zs40") or
            container.select_one(".c-abstract") or
            container.select_one(".content-right")
        )

        snippet = ""
        if abstract:
            snippet = abstract.get_text(" ", strip=True)
        else:
            spans = container.find_all("span")
            best_span = max(spans, key=lambda s: len(s.get_text(strip=True)), default=None)
            if best_span and len(best_span.get_text(strip=True)) > 20:
                snippet = best_span.get_text(" ", strip=True)

        snippet = snippet.replace("\n", " ").replace("\r", " ").strip()

        if title and url and len(title) > 3:
            raw_results.append({
                "source": "baidu",
                "rank": idx + 1,
                "title": title,
                "url": url,
                "snippet": snippet,
                "score": 1.0 / (idx + 1)
            })

    return raw_results


async def search_baidu(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    if not DP_AVAILABLE:
        print(f"[search_baidu {_ts()}] 警告: DrissionPage 未安装")
        return []

    if not BeautifulSoup:
        print(f"[search_baidu {_ts()}] Error: beautifulsoup4 not installed.")
        return []

    print(f"[search_baidu {_ts()}] 开始搜索: '{query}'")

    async with baidu_pool.acquire() as tab:
        try:
            def _do_search():
                print(f"[search_baidu {_ts()}] Step 1: 访问百度首页...")
                tab.get("https://www.baidu.com/")
                tab.wait(2)

                print(f"[search_baidu {_ts()}] Step 2: 定位搜索框...")
                search_input = None
                for sel in ['#kw', 'input[name="wd"]', 'input[type="text"]']:
                    try:
                        ele = tab.ele(sel, timeout=5)
                        if ele:
                            try:
                                tab.wait.ele_displayed(sel, timeout=2)
                            except Exception:
                                pass
                            search_input = ele
                            print(f"[search_baidu {_ts()}] 找到搜索框: {sel}")
                            break
                    except Exception:
                        continue

                if not search_input:
                    print(f"[search_baidu {_ts()}] 警告: 未找到搜索框，fallback 直接访问搜索 URL")
                    tab.get(f"https://www.baidu.com/s?wd={quote(query)}")
                    tab.wait(2)
                    return tab.html

                print(f"[search_baidu {_ts()}] Step 3: 输入查询词...")
                search_input.clear()
                search_input.input(query)
                tab.wait(0.5)

                print(f"[search_baidu {_ts()}] Step 4: 提交搜索...")
                try:
                    search_input.input('\n')
                except Exception as e:
                    print(f"[search_baidu {_ts()}] 输入回车失败（{e}），fallback 直接访问搜索 URL")
                    tab.get(f"https://www.baidu.com/s?wd={quote(query)}")
                    tab.wait(2)
                    return tab.html

                print(f"[search_baidu {_ts()}] Step 5: 等待结果页加载...")
                tab.wait(3)
                return tab.html

            print(f"[search_baidu {_ts()}] 进入浏览器操作（to_thread）...")
            html = await asyncio.to_thread(_do_search)
            print(f"[search_baidu {_ts()}] 浏览器操作完成，开始解析...")

            raw_results = _parse_baidu_results(html, top_k)

            if not raw_results:
                print(f"[search_baidu {_ts()}] 警告: 未找到与 '{query}' 相关的搜索结果")
                return []

            print(f"[search_baidu {_ts()}] 开始二次爬虫，共 {len(raw_results)} 条...")
            from core.search import fetch_page
            import requests
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
                ),
            }
            session = requests.Session()
            session.headers.update(headers)

            try:
                fetch_tasks = [fetch_page(session, r["url"]) for r in raw_results]
                full_texts = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            finally:
                session.close()

            final_results = []
            for r, full_text in zip(raw_results, full_texts):
                if isinstance(full_text, Exception):
                    full_text = ""

                content = full_text if len(full_text) >= 100 else r["snippet"]

                final_results.append({
                    "source": r["source"],
                    "rank": r["rank"],
                    "title": r["title"],
                    "url": r["url"],
                    "content": content,
                    "score": r["score"]
                })

            print(f"[search_baidu {_ts()}] 搜索完成，返回 {len(final_results)} 条结果")
            return final_results

        except Exception as e:
            print(f"[search_baidu {_ts()}] Error: {e}")
            import traceback
            traceback.print_exc()
            return []
