"""
Bing 搜索爬虫 — Tab Pool 并发复用
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

bing_pool = TabPool("bing", pool_size=5, base_port=9223)

def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def close_bing_browser():
    bing_pool.close_all()


def _parse_bing_results(html: str, top_k: int) -> List[Dict]:
    if not BeautifulSoup:
        return []

    soup = BeautifulSoup(html, "html.parser")
    raw_results = []
    items = soup.select("li.b_algo")

    print(f"[search_bing {_ts()}] 解析到 {len(items)} 个 li.b_algo 元素")

    for idx, item in enumerate(items[:top_k]):
        h2 = item.select_one("h2")
        if h2:
            a_tag = h2.select_one("a")
            if a_tag:
                title = a_tag.get_text(strip=True)
                url = a_tag.get("href", "")
            else:
                title = h2.get_text(strip=True)
                url = ""
        else:
            all_links = item.find_all("a")
            if not all_links:
                continue

            best_a = None
            best_len = 0
            for a in all_links:
                href = a.get("href", "")
                if not href or href.startswith("javascript:") or href.startswith("#"):
                    continue
                text = a.get_text(strip=True)
                if len(text) > best_len and len(text) > 5:
                    best_len = len(text)
                    best_a = a

            if not best_a:
                continue

            title = best_a.get_text(strip=True)
            url = best_a.get("href", "")

        caption = item.select_one(".b_caption")
        if not caption:
            caption = item.select_one(".b_snippet")

        if caption:
            for junk in caption.select(".b_attribution, .b_factrow, .b_vlist2col, .b_tpcn"):
                junk.decompose()
            snippet = caption.get_text(" ", strip=True)
        else:
            snippet = ""

        snippet = snippet.replace("\n", " ").replace("\r", " ").strip()

        if title and len(title) > 3 and not title.startswith("http"):
            raw_results.append({
                "source": "bing",
                "rank": idx + 1,
                "title": title,
                "url": url,
                "snippet": snippet,
                "score": 1.0 / (idx + 1)
            })

    return raw_results


async def search_bing(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    if not DP_AVAILABLE:
        print(f"[search_bing {_ts()}] 警告: DrissionPage 未安装")
        return []

    if not BeautifulSoup:
        print(f"[search_bing {_ts()}] Error: beautifulsoup4 not installed.")
        return []

    print(f"[search_bing {_ts()}] 开始搜索: '{query}'")

    async with bing_pool.acquire() as tab:
        try:
            def _do_search():
                print(f"[search_bing {_ts()}] Step 1: 访问 Bing 首页...")
                tab.get("https://www.bing.com/")
                tab.wait(2)

                print(f"[search_bing {_ts()}] Step 2: 定位搜索框...")

                search_input_selectors = [
                    'textarea[name="q"]',
                    'input[name="q"]',
                    '#sb_form_q',
                    'textarea#sb_form_q',
                    'input#sb_form_q',
                    '[aria-label="搜索"]',
                    '[placeholder*="搜索"]',
                ]

                search_input = None
                for selector in search_input_selectors:
                    try:
                        ele = tab.ele(selector, timeout=3)
                        if ele:
                            try:
                                tab.wait.ele_displayed(selector, timeout=2)
                            except Exception:
                                pass
                            search_input = ele
                            print(f"[search_bing {_ts()}] 找到搜索框: {selector}")
                            break
                    except Exception:
                        continue

                if not search_input:
                    print(f"[search_bing {_ts()}] 警告: 未找到搜索框，fallback 直接访问搜索 URL")
                    tab.get(f"https://www.bing.com/search?q={quote(query)}&setmkt=zh-cn&setlang=zh-cn")
                    tab.wait(2)
                    return tab.html

                print(f"[search_bing {_ts()}] Step 3: 输入查询词...")
                search_input.clear()
                search_input.input(query)
                tab.wait(0.5)

                print(f"[search_bing {_ts()}] Step 4: 提交搜索...")
                try:
                    search_input.input('\n')
                except Exception as e:
                    print(f"[search_bing {_ts()}] 输入回车失败（{e}），fallback 直接访问搜索 URL")
                    tab.get(f"https://www.bing.com/search?q={quote(query)}&setmkt=zh-cn&setlang=zh-cn")
                    tab.wait(2)
                    return tab.html

                print(f"[search_bing {_ts()}] Step 5: 等待结果页加载...")
                tab.wait(3)
                return tab.html

            print(f"[search_bing {_ts()}] 进入浏览器操作（to_thread）...")
            html = await asyncio.to_thread(_do_search)
            print(f"[search_bing {_ts()}] 浏览器操作完成，开始解析...")

            raw_results = _parse_bing_results(html, top_k)

            if not raw_results:
                print(f"[search_bing {_ts()}] 警告: 未找到与 '{query}' 相关的搜索结果")
                return []

            print(f"[search_bing {_ts()}] 开始二次爬虫，共 {len(raw_results)} 条...")
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

                if len(full_text) >= 100:
                    content = full_text
                else:
                    content = r["snippet"]

                final_results.append({
                    "source": r["source"],
                    "rank": r["rank"],
                    "title": r["title"],
                    "url": r["url"],
                    "content": content,
                    "score": r["score"]
                })

            print(f"[search_bing {_ts()}] 搜索完成，返回 {len(final_results)} 条结果")
            return final_results

        except Exception as e:
            print(f"[search_bing {_ts()}] Error: {e}")
            import traceback
            traceback.print_exc()
            return []
