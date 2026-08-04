#!/usr/bin/env python3
"""
一键导入脚本：将极空间共享目录中的文档解析、分段、向量化后存入 Chroma。
支持增量检测（新增、修改、删除）。
"""
import os
import sys
import json
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import get_settings
from core.chroma_client import get_collection, OllamaEmbeddingFunction
from core.document_loader import load_document, get_file_hash

settings = get_settings()

KB_ROOT = os.getenv("KB_ROOT", r"Z:\逻各斯的知识库")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LOG_PATH = os.path.join(DATA_DIR, "ingest_log.json")
os.makedirs(DATA_DIR, exist_ok=True)


def load_log() -> Dict[str, Any]:
    if not os.path.exists(LOG_PATH):
        return {}
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_log(log: Dict[str, Any]):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def scan_files(root: str) -> List[str]:
    supported = (".docx", ".pdf", ".txt", ".md", ".markdown", ".xlsx", ".xls")
    files = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(supported):
                files.append(os.path.join(dirpath, fn))
    return files


def compute_file_meta(filepath: str) -> Dict[str, Any]:
    stat = os.stat(filepath)
    return {
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "hash": get_file_hash(filepath),
    }


def preflight_check() -> bool:
    """入库前预检：确认 Ollama embedding 可用"""
    print("[预检] 测试 Ollama embedding...")
    try:
        fn = OllamaEmbeddingFunction()
        emb = fn._embed_single("测试")
        if emb and len(emb) > 0:
            print(f"  ✅ 正常，维度: {len(emb)}")
            return True
        print("  ❌ 返回空向量")
        return False
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False


def main():
    print("=" * 50)
    print("Λόγος 知识库导入脚本")
    print(f"扫描目录: {KB_ROOT}")
    print(f"Chroma 路径: {os.path.abspath(settings.CHROMA_DB_PATH)}")
    print(f"Ollama 地址: {settings.OLLAMA_HOST}")
    print("=" * 50)
    
    if not os.path.exists(KB_ROOT):
        print(f"[错误] 目录不存在: {KB_ROOT}")
        sys.exit(1)
    
    if not preflight_check():
        print("\n[终止] Ollama 不可用。请在 Mac Studio 上执行: ollama run bge-m3:latest")
        sys.exit(1)
    
    collection = get_collection()
    log = load_log()
    files = scan_files(KB_ROOT)
    print(f"发现 {len(files)} 个文档")
    
    # 清理已删除文件
    deleted = [p for p in log if p not in files]
    for filepath in deleted:
        ids = log[filepath].get("chroma_ids", [])
        if ids:
            try:
                collection.delete(ids=ids)
                print(f"  [清理] {os.path.basename(filepath)} ({len(ids)} chunks)")
            except Exception as e:
                print(f"  [清理失败] {e}")
        del log[filepath]
    
    new_count = update_count = skip_count = 0
    
    for filepath in files:
        rel_path = os.path.relpath(filepath, KB_ROOT)
        file_meta = compute_file_meta(filepath)
        
        if filepath in log:
            old = log[filepath]
            if old.get("hash") == file_meta["hash"] and old.get("mtime") == file_meta["mtime"]:
                skip_count += 1
                continue
            old_ids = old.get("chroma_ids", [])
            if old_ids:
                try:
                    collection.delete(ids=old_ids)
                except Exception as e:
                    print(f"  [清理旧向量失败] {e}")
            update_count += 1
        else:
            new_count += 1
        
        print(f"\n[处理] {rel_path}")
        
        try:
            chunks = load_document(filepath)
        except Exception as e:
            print(f"  [解析失败] {e}")
            continue
        
        if not chunks:
            print("  [跳过] 无内容")
            continue
        
        print(f"  生成 {len(chunks)} 个文本块，正在向量化...")
        
        ids, documents, metadatas = [], [], []
        
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{file_meta['hash']}_{idx}"
            ids.append(chunk_id)
            documents.append(chunk["text"])
            
            # ====== 核心修复：doc_meta 彻底隔离，None 值不入库 ======
            doc_meta = {
                "source": filepath,
                "filename": os.path.basename(filepath),
                "title": chunk.get("title") or os.path.basename(filepath),
                "chunk_index": idx,
            }
            if chunk.get("page") is not None:
                doc_meta["page"] = chunk["page"]
            if chunk.get("sheet") is not None:
                doc_meta["sheet"] = chunk["sheet"]
            metadatas.append(doc_meta)
            # =====================================================
        
        try:
            collection.add(ids=ids, documents=documents, metadatas=metadatas)
            log[filepath] = {
                "mtime": file_meta["mtime"],
                "size": file_meta["size"],
                "hash": file_meta["hash"],
                "chroma_ids": ids,
            }
            print(f"  [成功] 写入 {len(ids)} 条向量")
        except Exception as e:
            print(f"  [入库失败] {e}")
    
    save_log()
    
    print(f"\n{'='*50}")
    print(f"导入完成: 新增 {new_count} | 更新 {update_count} | 跳过 {skip_count} | 清理 {len(deleted)}")
    print(f"日志: {LOG_PATH}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()