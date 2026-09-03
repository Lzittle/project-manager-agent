"""reset_demo.py — 一键重置演示环境：清空 SQLite 与 ChromaDB → 建表 → seed（含文档向量化）。

用法（backend/ 目录下）:
    python reset_demo.py
注意：需在应用未运行时执行（本机请先停掉 uvicorn 8000）。
"""
import os
import re
import shutil
from pathlib import Path


def main() -> None:
    # 延迟导入：config 需在本模块先就绪后由各依赖按需加载
    from core.config import settings

    # 1) 删除旧 SQLite
    m = re.match(r"sqlite:///(.+)$", settings.DATABASE_URL)
    db_path = None
    if m:
        # Windows 盘符路径形如 D:/...；统一转 Path
        raw = m.group(1).replace("/", os.sep) if ":" not in m.group(1) else m.group(1)
        db_path = Path(raw)
        if db_path.exists():
            db_path.unlink()
            print(f"[1/4] 已删除数据库: {db_path}")

    # 2) 删除旧 ChromaDB 目录
    chroma_dir = Path(settings.CHROMA_PERSIST_DIR)
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
        print(f"[2/4] 已删除向量库目录: {chroma_dir}")

    # 3) 建表
    from models.database import init_db
    init_db()
    print("[3/4] 已重建 6 张业务表")

    # 4) 灌入演示数据（含文档向量化）
    import seed
    seed.seed()
    print("[4/4] 演示环境重置完成 ✅")
    print("     下一步：python -m uvicorn main:app --reload 启动后端")


if __name__ == "__main__":
    main()
