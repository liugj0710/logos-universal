# core/search.py
"""
搜索层统一入口。

文件结构（避免后续 Kimi 产生幻觉）：
- search.py          <- 本文件：通用工具函数（正文提取、清洗、抓取）+ 统一入口
- search_bing.py     <- Bing 搜索（DrissionPage 浏览器自动化，独立文件）
- search_baidu.py    <- 百度搜索（DrissionPage 浏览器自动化，独立文件）
- search_chroma.py   <- Chroma 向量检索（独立文件）
- search_dify.py     <- Dify 知识库检索（独立文件）
- fusion.py          <- RRF 融合 + 语义去重

【为什么拆成多个文件？】
Bing 和百度的反爬策略完全不同：
- Bing: 检测 TLS/HTTP 指纹和 JS 执行环境，必须用真实浏览器（DrissionPage）
- 百度: 反爬宽松，requests 即可稳定获取结果（注：当前已统一用 DrissionPage）
- Dify: 调用 REST API，独立文件便于维护

拆分为独立文件后，后续维护者可以单独优化某一源，而不会误改另一源。
"""

import os
import re
import asyncio
import requests
from typing import List, Dict, Any

try:
    from bs4 import BeautifulSoup, Comment
except ImportError:
    BeautifulSoup = None
    Comment = None

# ========== 通用工具函数（供 search_bing.py 和 search_baidu.py 导入）==========

NOISE_PATTERNS = [
    re.compile(r"登录|注册|忘记密码|验证码", re.I),
    re.compile(r"相关推荐|猜你喜欢|热门文章|推荐阅读", re.I),
    re.compile(r"©|版权所有|免责声明|隐私政策|关于我们|联系我们", re.I),
    re.compile(r"^\s*分享\s*[到至]?\s*(微信|微博|QQ|朋友圈)", re.I),
    re.compile(r"^\s*点赞|收藏|评论|转发", re.I),
]

def is_noise(text: str) -> bool:
    """判断一段文本是否为噪声"""
    text = text.strip()
    if len(text) < 10:
        return True
    for pat in NOISE_PATTERNS:
        if pat.search(text):
            return True
    return False

def extract_article(html: str) -> str:
    """
    从 HTML 中提取正文内容。
    策略：article > main > 常见内容容器 > 密度算法 > 所有 p 标签
    """
    if not html or not BeautifulSoup:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # 移除 script, style, nav, footer, aside, header, comment
    for tag in soup.find_all(["script", "style", "nav", "footer", "aside", "header"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 策略1：优先 <article>
    article = soup.find("article")
    if article:
        text = article.get_text(" ", strip=True)
        if len(text) > 100:
            return text

    # 策略2：<main>
    main = soup.find("main")
    if main:
        text = main.get_text(" ", strip=True)
        if len(text) > 100:
            return text

    # 策略3：常见内容类名/ID
    content_selectors = [
        "div.content", "div.post-content", "div.article-content",
        "div.entry-content", "div.main-content", "div.text",
        "div#content", "div#article", "div#post",
        "div.article", "div.post", "div.main"
    ]
    for sel in content_selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(" ", strip=True)
            if len(text) > 100:
                return text

    # 策略4：密度算法 — 找文本/标签比最高的 div
    best_div = None
    best_score = 0
    for div in soup.find_all("div"):
        text_len = len(div.get_text(strip=True))
        tag_count = len(div.find_all())
        if tag_count == 0:
            continue
        score = text_len / (tag_count + 1)
        if score > best_score and text_len > 200:
            best_score = score
            best_div = div

    if best_div:
        text = best_div.get_text(" ", strip=True)
        if len(text) > 100:
            return text

    # 策略5：兜底 — 所有 p 标签拼接
    paragraphs = []
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True)
        if txt and not is_noise(txt):
            paragraphs.append(txt)

    if paragraphs:
        return " ".join(paragraphs)

    return ""

def clean_text(text: str, max_len: int = 3000) -> str:
    """清洗并截断文本"""
    if not text:
        return ""

    # 统一空白
    text = re.sub(r"\s+", " ", text)

    # 按句子/段落截断到 max_len
    if len(text) > max_len:
        cut = text.rfind("。", 0, max_len)
        if cut == -1:
            cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = text.rfind(" ", 0, max_len)
        if cut == -1:
            cut = max_len
        text = text[:cut]

    return text.strip()

async def fetch_page(session: requests.Session, url: str, timeout: int = 5) -> str:
    """异步抓取单页正文"""
    try:
        def _get():
            return session.get(url, timeout=timeout, allow_redirects=True)

        resp = await asyncio.to_thread(_get)

        if resp.status_code != 200:
            return ""

        # 简单编码处理
        if resp.encoding == "ISO-8859-1":
            resp.encoding = resp.apparent_encoding

        html = resp.text
        raw_text = extract_article(html)
        return clean_text(raw_text)

    except Exception as e:
        print(f"[fetch_page] Error fetching {url}: {e}")
        return ""

# ========== 统一搜索入口 ==========

async def search_all_sources(query: str, top_k: int = 10, skill_hint: str = "default_deep") -> List[Dict[str, Any]]:
    """
    统一搜索入口：Bing + 百度 + Chroma + Dify KB
    去重 + 内容过滤（<200字丢弃）
    """
    # v0.2.2 修复：惰性导入，避免模块加载时触发 chromadb 等依赖
    from core.search_bing import search_bing
    from core.search_baidu import search_baidu
    from core.search_chroma import search_chroma
    from core.search_dify import search_dify_kb
    from core.fusion import rrf_fusion, deduplicate_by_content

    tasks = [
        search_bing(query, top_k),
        search_baidu(query, top_k),
        search_chroma(query, top_k, skill_hint),
        search_dify_kb(query, top_k)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results = []
    for r in results:
        if isinstance(r, list):
            all_results.extend(r)
        else:
            print(f"[search_all_sources] Source error: {r}")

    # 去重：基于 URL，保留 content 更长的版本
    seen_urls = {}
    for r in all_results:
        url = r.get("url", "")
        if not url:
            continue
        if url in seen_urls:
            if len(r.get("content", "")) > len(seen_urls[url].get("content", "")):
                seen_urls[url] = r
        else:
            seen_urls[url] = r

    deduped = list(seen_urls.values())

    # 内容过滤：正文少于 200 字的结果丢弃
    # 避免 Agent 拿到"凑数"的低质量结果，误判为"资料不足"
    filtered = [r for r in deduped if len(r.get("content", "")) >= 200]

    # 按 score 降序
    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    return filtered[:top_k]

# ========== 子模块导入（延迟加载，避免 chromadb 等依赖在模块加载时触发）==========

from core.search_bing import search_bing
from core.search_baidu import search_baidu

async def search_chroma(*args, **kwargs):
    try:
        from core.search_chroma import search_chroma as _sc
        return await _sc(*args, **kwargs)
    except ImportError as e:
        print(f"[search_chroma] 依赖缺失: {e}")
        return []

async def search_dify_kb(*args, **kwargs):
    try:
        from core.search_dify import search_dify_kb as _sd
        return await _sd(*args, **kwargs)
    except ImportError as e:
        print(f"[search_dify_kb] 依赖缺失: {e}")
        return []