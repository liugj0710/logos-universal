# D:\precision_agent\core\graphrag\extractor.py
"""
GraphRAG 实体关系抽取引擎
使用 DeepSeek-V4 Flash 进行零样本 NER + RE
支持长文本分块抽取、结果合并
v0.4.4-fix3: 批量抽取修复 — few-shot prompt + 增强解析 + 并行 fallback
"""
import asyncio
import json
import re
from typing import List, Dict, Any, Tuple, Optional

from core.llm import call_llm

# ───────────────────────────────────────────────
# 实体类型定义
# ───────────────────────────────────────────────

ENTITY_TYPES = {
    "PERSON": "人员/角色/岗位",
    "ORG": "组织/机构/企业/部门",
    "TECH": "技术/设备/系统/装置",
    "CONCEPT": "概念/理论/方法/流程",
    "EVENT": "事件/活动/项目/事故",
    "LOCATION": "地点/场所/区域",
    "REGULATION": "法规/标准/规程/制度",
    "PRODUCT": "产品/型号/材料",
    "METRIC": "指标/参数/数值/阈值"
}

# ───────────────────────────────────────────────
# 关系类型定义
# ───────────────────────────────────────────────

RELATION_TYPES = {
    "belongs_to": "属于",
    "operates": "操作/运维",
    "supplies": "供电/供应",
    "contains": "包含",
    "regulates": "规范/约束",
    "measures": "测量/监测",
    "causes": "导致",
    "prevents": "预防",
    "requires": "需要/依赖",
    "produces": "产生",
    "locates_at": "位于",
    "part_of": "组成部分",
    "implements": "实施",
    "evaluates": "评估",
    "connects_to": "关联"
}

# ───────────────────────────────────────────────
# Prompt 模板（精简）
# ───────────────────────────────────────────────

_EXTRACTION_SYSTEM_PROMPT = f"""从文本中抽取实体和关系，输出JSON。

实体类型：PERSON,ORG,TECH,CONCEPT,EVENT,LOCATION,REGULATION,PRODUCT,METRIC
关系类型：belongs_to,operates,supplies,contains,regulates,measures,causes,prevents,requires,produces,locates_at,part_of,implements,evaluates,connects_to

规则：
1. 只抽文本中明确提及的具体对象
2. 关系必须基于明确表述，不推断隐含关系
3. 每个实体和关系必须标注 confidence(0.0-1.0)
4. 如无实体或关系，返回空数组
5. description 限制30字以内

输出格式（严格JSON，无额外文字）：
{{"entities":[{{"name":"","type":"","description":"","confidence":0.9}}],"relations":[{{"source":"","target":"","relation_type":"","description":"","confidence":0.9}}]}}"""


# ───────────────────────────────────────────────
# 核心函数
# ───────────────────────────────────────────────

async def extract_entities_relations(
    text: str,
    source_chunk: str = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    从文本中抽取实体和关系。
    如果文本过长（>3000字），自动分块抽取后合并。
    """
    if not text or len(text.strip()) < 30:
        print(f"[extractor] 跳过过短文本 (length={len(text) if text else 0})")
        return [], []

    if len(text) <= 3000:
        return await _extract_single(text, source_chunk)

    chunks = _split_text(text, max_len=2500, overlap=200)
    print(f"[extractor] 长文本分块: {len(chunks)} 块")
    all_entities = []
    all_relations = []

    for i, chunk in enumerate(chunks):
        print(f"[extractor] 处理第 {i+1}/{len(chunks)} 块 (length={len(chunk)})")
        entities, relations = await _extract_single(chunk, source_chunk)
        all_entities.extend(entities)
        all_relations.extend(relations)

    merged_entities = _merge_entities(all_entities)
    merged_relations = _merge_relations(all_relations)
    print(f"[extractor] 长文本合并结果: entities={len(merged_entities)}, relations={len(merged_relations)}")

    return merged_entities, merged_relations


async def _extract_single(text: str, source_chunk: str = None,
                          attempt: int = 1, max_attempts: int = 2) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """单块文本抽取，带重试"""
    try:
        print(f"[extractor] 调用 LLM 抽取，文本长度: {len(text)} (attempt {attempt}/{max_attempts})")
        response = await call_llm(
            model="deepseek-v4-flash",
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=f"请从以下文本中抽取实体和关系：\n\n{text[:3500]}",
            temperature=0.2,
            max_tokens=4000,
            json_mode=True
        )

        if not response:
            print(f"[extractor] 警告: LLM 返回空 (attempt {attempt})")
            if attempt < max_attempts:
                import asyncio
                await asyncio.sleep(1)
                return await _extract_single(text, source_chunk, attempt + 1, max_attempts)
            return [], []

        print(f"[extractor] LLM 返回长度: {len(response)}")

        stripped = response.strip()
        if not (stripped.endswith("}") or stripped.endswith("]")):
            print(f"[extractor] 警告: 响应可能被截断（末尾: ...{stripped[-30:]}）")
            if attempt < max_attempts:
                import asyncio
                await asyncio.sleep(1)
                return await _extract_single(text, source_chunk, attempt + 1, max_attempts)

        result = _safe_parse_json(response)
        print(f"[extractor] JSON 解析结果: keys={list(result.keys())}")

        raw_entities = result.get("entities", [])
        raw_relations = result.get("relations", [])
        print(f"[extractor] 原始抽取: entities={len(raw_entities)}, relations={len(raw_relations)}")

        entities = _validate_entities(raw_entities)
        relations = _validate_relations(raw_relations)
        print(f"[extractor] 验证后: entities={len(entities)}, relations={len(relations)}")

        return entities, relations

    except Exception as e:
        print(f"[extractor] 抽取异常: {e}")
        if attempt < max_attempts:
            import asyncio
            await asyncio.sleep(1)
            return await _extract_single(text, source_chunk, attempt + 1, max_attempts)
        import traceback
        traceback.print_exc()
        return [], []


def _split_text(text: str, max_len: int = 2500, overlap: int = 200) -> List[str]:
    """按句子边界分块"""
    sentences = re.split(r"([。！？\n]+)", text)
    chunks = []
    current = ""

    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        sep = sentences[i + 1] if i + 1 < len(sentences) else ""
        fragment = sentence + sep

        if len(current) + len(fragment) > max_len and current:
            chunks.append(current)
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:]
            else:
                current = ""

        current += fragment

    if current:
        chunks.append(current)

    return chunks if chunks else [text]


def _safe_parse_json(text: str) -> Dict[str, Any]:
    """安全解析 JSON，多层 fallback"""
    if not text:
        return {}

    text = text.strip()

    # 策略1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[extractor] 直接 JSON 解析失败: {e}")

    # 策略2: 提取 ```json 代码块
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # 策略3: 提取最外层花括号
    matches = list(re.finditer(r"\{.*?\}", text, re.DOTALL))
    matches.sort(key=lambda m: len(m.group(0)), reverse=True)
    for match in matches:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue

    # 策略4: 尝试修复常见 JSON 截断问题
    fixed = _fix_truncated_json(text)
    if fixed:
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    print(f"[extractor] JSON 解析全部失败，原始内容前300字: {text[:300]}")
    return {}


def _fix_truncated_json(text: str) -> str:
    """尝试修复被截断的 JSON"""
    text = text.strip()
    if not text.startswith("{"):
        return ""

    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")

    fixed = text
    for _ in range(max(0, open_braces)):
        fixed += "}"
    for _ in range(max(0, open_brackets)):
        fixed += "]"

    if open_braces > 0 or open_brackets > 0:
        candidates = [
            fixed.rfind('",'),
            fixed.rfind('"}'),
            fixed.rfind("]}"),
            fixed.rfind("}}"),
            fixed.rfind("]}]")
        ]
        last_complete = max(c for c in candidates if c > 0) if any(c > 0 for c in candidates) else -1

        if last_complete > 0:
            truncated = fixed[:last_complete + 2]
            if '"entities"' in truncated and '"relations"' not in truncated:
                truncated += '],"relations":[]}'
            elif '"relations"' in truncated:
                truncated += ']}'
            else:
                truncated += "}"
            return truncated

    return fixed


def _validate_entities(entities: List[Any]) -> List[Dict[str, Any]]:
    """清洗和验证实体列表"""
    valid = []
    seen = set()

    for e in entities:
        if not isinstance(e, dict):
            print(f"[extractor] 跳过非 dict 实体: {type(e)}")
            continue

        name = str(e.get("name", "")).strip()
        if not name or len(name) < 2:
            print(f"[extractor] 跳过无效实体名: '{name}'")
            continue

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        etype = str(e.get("type", "CONCEPT")).upper()
        if etype not in ENTITY_TYPES:
            print(f"[extractor] 未知实体类型 '{etype}'，降级为 CONCEPT")
            etype = "CONCEPT"

        confidence = float(e.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        valid.append({
            "name": name,
            "type": etype,
            "description": str(e.get("description", ""))[:50],
            "confidence": round(confidence, 3)
        })

    return valid


def _validate_relations(relations: List[Any]) -> List[Dict[str, Any]]:
    """清洗和验证关系列表"""
    valid = []
    seen = set()

    for r in relations:
        if not isinstance(r, dict):
            print(f"[extractor] 跳过非 dict 关系: {type(r)}")
            continue

        source = str(r.get("source", "")).strip()
        target = str(r.get("target", "")).strip()
        if not source or not target or source == target:
            print(f"[extractor] 跳过无效关系: source='{source}', target='{target}'")
            continue

        rel_type = str(r.get("relation_type", "connects_to")).lower()
        if rel_type not in RELATION_TYPES:
            print(f"[extractor] 未知关系类型 '{rel_type}'，降级为 connects_to")
            rel_type = "connects_to"

        key = (source.lower(), target.lower(), rel_type)
        if key in seen:
            continue
        seen.add(key)

        confidence = float(r.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        valid.append({
            "source": source,
            "target": target,
            "relation_type": rel_type,
            "description": str(r.get("description", ""))[:40],
            "confidence": round(confidence, 3)
        })

    return valid


def _merge_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并重复实体（基于名称相似度）"""
    from difflib import SequenceMatcher

    merged = []

    for e in entities:
        name = e["name"]
        merged_with = None

        for m in merged:
            sim = SequenceMatcher(None, name.lower(), m["name"].lower()).ratio()
            if sim >= 0.85 and e["type"] == m["type"]:
                merged_with = m
                break

        if merged_with:
            if len(e.get("description", "")) > len(merged_with.get("description", "")):
                merged_with["description"] = e["description"]
            merged_with["confidence"] = max(merged_with.get("confidence", 0), e.get("confidence", 0))
        else:
            merged.append(dict(e))

    return merged


def _merge_relations(relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并重复关系（权重累加）"""
    merged_map = {}

    for r in relations:
        key = (r["source"].lower(), r["target"].lower(), r["relation_type"])

        if key in merged_map:
            existing = merged_map[key]
            existing["weight"] = existing.get("weight", 1) + 1
            existing["confidence"] = max(existing.get("confidence", 0), r.get("confidence", 0))
            if len(r.get("description", "")) > len(existing.get("description", "")):
                existing["description"] = r["description"]
        else:
            merged_map[key] = dict(r)
            merged_map[key]["weight"] = 1

    return list(merged_map.values())


# ───────────────────────────────────────────────
# v0.4.4-fix3: 批量抽取（few-shot + 增强解析 + 并行 fallback）
# ───────────────────────────────────────────────

_BATCH_EXTRACTION_SYSTEM_PROMPT = """你是一个信息抽取专家。请从提供的多段文本中分别抽取实体和关系。

【实体类型】PERSON(人员), ORG(组织), TECH(技术/设备), CONCEPT(概念), EVENT(事件), LOCATION(地点), REGULATION(法规), PRODUCT(产品), METRIC(指标)
【关系类型】belongs_to, operates, supplies, contains, regulates, measures, causes, prevents, requires, produces, locates_at, part_of, implements, evaluates, connects_to

【抽取规则】
1. 对每段文本分别抽取，用 chunk_id 区分，不要混淆不同文本的内容
2. 只抽取文本中明确提及的具体对象，不要推断隐含关系
3. 每个 chunk 最多输出 6 个实体、4 个关系，控制总长度避免截断
4. 每个实体和关系必须标注 confidence(0.0-1.0)
5. description 限制15字以内

【输出格式 - 必须严格遵守】
1. 使用 ```json 代码块包裹输出
2. 顶层必须是 {"results": [...]} 结构
3. 数组中每个对象对应一个 chunk，必须包含 chunk_id、entities、relations 三个字段

【示例】
输入文本：
---CHUNK_ID: doc_001---
张三在北京大学计算机学院工作，他研究人工智能和深度学习。

---CHUNK_ID: doc_002---
王五管理销售部门，该部门负责华东区的客户拓展。

输出：
```json
{"results":[
  {"chunk_id":"doc_001","entities":[{"name":"张三","type":"PERSON","description":"研究人员","confidence":0.95},{"name":"北京大学计算机学院","type":"ORG","description":"高校学院","confidence":0.9},{"name":"人工智能","type":"TECH","description":"技术领域","confidence":0.9},{"name":"深度学习","type":"CONCEPT","description":"AI子领域","confidence":0.85}],"relations":[{"source":"张三","target":"北京大学计算机学院","relation_type":"belongs_to","description":"工作于","confidence":0.9},{"source":"张三","target":"人工智能","relation_type":"operates","description":"研究","confidence":0.85},{"source":"人工智能","target":"深度学习","relation_type":"contains","description":"包含","confidence":0.8}]},
  {"chunk_id":"doc_002","entities":[{"name":"王五","type":"PERSON","description":"管理者","confidence":0.9},{"name":"销售部门","type":"ORG","description":"企业部门","confidence":0.9},{"name":"华东区","type":"LOCATION","description":"地理区域","confidence":0.85}],"relations":[{"source":"王五","target":"销售部门","relation_type":"operates","description":"管理","confidence":0.9},{"source":"销售部门","target":"华东区","relation_type":"locates_at","description":"负责区域","confidence":0.8}]}
]}
```

现在请处理以下文本，确保输出格式与示例完全一致："""


def _safe_parse_batch_results(text: str, expected_cids: List[str]) -> Dict[str, Tuple[Optional[List[Dict]], Optional[List[Dict]]]]:
    """
    从 LLM 输出中解析 batch 抽取结果。
    支持: {"results":[...]}、扁平数组、分散 JSON 对象、代码块嵌套。
    返回: {chunk_id: (entities, relations)}，未找到的 cid 值设为 (None, None)
    """
    if not text:
        return {cid: (None, None) for cid in expected_cids}

    text = text.strip()
    result_map: Dict[str, Tuple[Optional[List], Optional[List]]] = {}

    # ── 策略1: 标准 JSON 解析（含代码块提取）──
    candidates = [text]
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block.startswith("{") or block.startswith("["):
                candidates.append(block)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                for item in data["results"]:
                    if isinstance(item, dict):
                        cid = str(item.get("chunk_id", "")).strip()
                        if cid:
                            result_map[cid] = (
                                _validate_entities(item.get("entities", [])),
                                _validate_relations(item.get("relations", []))
                            )
                if result_map:
                    break
            # 扁平数组格式
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        cid = str(item.get("chunk_id", "")).strip()
                        if cid:
                            result_map[cid] = (
                                _validate_entities(item.get("entities", [])),
                                _validate_relations(item.get("relations", []))
                            )
                if result_map:
                    break
        except (json.JSONDecodeError, ValueError):
            continue

    # ── 策略2: 正则提取所有含 chunk_id 的 {...} 对象 ──
    if not result_map:
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    snippet = text[start:i+1]
                    try:
                        obj = json.loads(snippet)
                        if isinstance(obj, dict) and "chunk_id" in obj:
                            cid = str(obj["chunk_id"]).strip()
                            result_map[cid] = (
                                _validate_entities(obj.get("entities", [])),
                                _validate_relations(obj.get("relations", []))
                            )
                    except (json.JSONDecodeError, ValueError):
                        pass
                    start = -1

    # ── 策略3: 尝试修复截断的 results 数组 ──
    if not result_map:
        fixed = _fix_truncated_json(text)
        if fixed and fixed != text:
            try:
                data = json.loads(fixed)
                if isinstance(data, dict) and "results" in data:
                    for item in data["results"]:
                        if isinstance(item, dict):
                            cid = str(item.get("chunk_id", "")).strip()
                            if cid:
                                result_map[cid] = (
                                    _validate_entities(item.get("entities", [])),
                                    _validate_relations(item.get("relations", []))
                                )
            except (json.JSONDecodeError, ValueError):
                pass

    # 补全未找到的 cid
    for cid in expected_cids:
        if cid not in result_map:
            result_map[cid] = (None, None)

    return result_map


def _guess_relation_type(description: str) -> str:
    """从关系描述猜测预定义关系类型"""
    desc = description.lower()
    mapping = [
        (["属于", "归属", "member", "part", "组成"], "belongs_to"),
        (["操作", "运维", "运行", "管理", "operat", "manage", "work"], "operates"),
        (["供电", "供应", "提供", "supply", "power", "feed"], "supplies"),
        (["包含", "包括", "contain", "include"], "contains"),
        (["规范", "约束", "限制", "regul", "rule", "standard"], "regulates"),
        (["测量", "监测", "检测", "measur", "monitor", "test"], "measures"),
        (["导致", "引起", "造成", "caus", "lead", "result"], "causes"),
        (["预防", "防止", "避免", "prevent", "protect"], "prevents"),
        (["需要", "依赖", "require", "depend", "need"], "requires"),
        (["产生", "生成", "produc", "generat", "create"], "produces"),
        (["位于", "位置", "locat", "place", "site"], "locates_at"),
        (["部分", "组成", "component"], "part_of"),
        (["实施", "执行", "implement", "deploy"], "implements"),
        (["评估", "评价", "evaluat", "assess"], "evaluates"),
    ]
    for keywords, rel_type in mapping:
        if any(kw in desc for kw in keywords):
            return rel_type
    return "connects_to"


async def _fallback_batch_extract(items: List[Tuple[str, str]]) -> List[Tuple[List[Dict], List[Dict], str]]:
    """
    并行 fallback 单条抽取，限制并发避免超时累积。
    Semaphore(3) x 30s = 最坏情况约 30s（而非 45sxN）
    """
    sem = asyncio.Semaphore(3)

    async def _do_one(text: str, cid: str):
        async with sem:
            try:
                entities, relations = await asyncio.wait_for(
                    extract_entities_relations(text, cid),
                    timeout=30.0
                )
                print(f"[extractor_batch] fallback 成功: {cid}, entities={len(entities)}")
                return (entities, relations, cid)
            except asyncio.TimeoutError:
                print(f"[extractor_batch] fallback 单条超时: {cid}")
                return ([], [], cid)
            except Exception as e:
                print(f"[extractor_batch] fallback 单条异常: {cid}, {e}")
                return ([], [], cid)

    tasks = [_do_one(text, cid) for text, cid in items]
    return await asyncio.gather(*tasks)


async def extract_entities_relations_batch(
    items: List[Tuple[str, Optional[str]]],
    max_batch_len: int = 1800,
    max_items_per_batch: int = 2
) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]]:
    """
    批量抽取实体关系，减少 LLM 调用次数。
    v0.4.4-fix3: few-shot prompt + 增强解析 + 并行 fallback
    """
    if not items:
        return []

    # 按长度分组（每批最多 2 个，总长度 < 1800）
    batches: List[List[Tuple[str, str]]] = []
    current_batch: List[Tuple[str, str]] = []
    current_len = 0

    for text, cid in items:
        tlen = len(text)
        if (current_len + tlen > max_batch_len or len(current_batch) >= max_items_per_batch) and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_len = 0
        current_batch.append((text, cid or f"batch_chunk_{len(current_batch)}"))
        current_len += tlen

    if current_batch:
        batches.append(current_batch)

    all_results: List[Tuple[List[Dict], List[Dict], str]] = []

    for batch_idx, batch in enumerate(batches):
        texts = []
        for text, cid in batch:
            texts.append(f"---CHUNK_ID: {cid}---\n{text}")

        prompt = "\n\n".join(texts)
        expected_cids = [cid for _, cid in batch]

        try:
            response = await call_llm(
                model="deepseek-v4-flash",
                system_prompt=_BATCH_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=f"请从以下 {len(batch)} 段文本中分别抽取实体和关系：\n\n{prompt}",
                temperature=0.1,  # 降低温度提高格式稳定性
                max_tokens=4000,
                json_mode=False
            )

            resp_len = len(response) if response else 0
            print(f"[extractor_batch] 批次 #{batch_idx+1}/{len(batches)} ({len(batch)} chunks), LLM 返回长度: {resp_len}")

            if not response:
                raise ValueError("LLM 返回空")

            # 使用增强的 batch 解析器
            result_map = _safe_parse_batch_results(response, expected_cids)
            found_cids = [cid for cid, (ents, rels) in result_map.items() if ents is not None]
            print(f"[extractor_batch] 解析到 {len(found_cids)}/{len(expected_cids)} 个 chunk 结果")

            # 按原始 batch 顺序输出
            missing_items = []
            for text, cid in batch:
                entities, relations = result_map.get(cid, (None, None))
                if entities is None:
                    missing_items.append((text, cid))
                    print(f"[extractor_batch] {cid}: 未在 batch 结果中找到，标记为 missing")
                else:
                    print(f"[extractor_batch] {cid}: entities={len(entities)}, relations={len(relations)}")
                    all_results.append((entities, relations, cid))

            # 对 missing 的 chunk 并行 fallback
            if missing_items:
                print(f"[extractor_batch] {len(missing_items)} 个 chunk 进入并行 fallback")
                fallback_results = await _fallback_batch_extract(missing_items)
                all_results.extend(fallback_results)

        except Exception as e:
            print(f"[extractor_batch] 批量抽取整体失败: {e}，全部回退到并行单条抽取")
            fallback_results = await _fallback_batch_extract(batch)
            all_results.extend(fallback_results)

    return all_results
