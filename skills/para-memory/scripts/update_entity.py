#!/usr/bin/env python3
"""
Add or update facts in an entity's items.json.

Usage: python update_entity.py <entity_path> --add <fact_json>
       python update_entity.py <entity_path> --supersede <old_fact_id> <new_fact_json>

写入纪律（对应 spec/ParaMemory.tla 的两条不变量）：

  P1 AtomicSupersede —— 一次 supersede 的所有改动（新事实、旧事实状态、supersededBy）
                        在内存里算完，只落盘一次；崩溃不会留下「两个 active」。
  P2 NoLostUpdate    —— 同一实体的读-改-写在一把排他锁里（flock），
                        并发写不会互相覆盖，fact id 也不会撞。

落盘用「写 .tmp + os.replace」：同目录 rename 在 POSIX 上是原子的，
读者要么看到旧文件、要么看到新文件，不会读到写了一半的 JSON。
"""

import sys
import json
import os
import contextlib
from pathlib import Path
from datetime import datetime
import argparse

try:  # POSIX 才有的排他锁；Windows 上退化为「只有原子写、没有互斥」
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

REQUIRED_FIELDS = ("fact", "category", "timestamp", "source")


@contextlib.contextmanager
def entity_lock(entity_path):
    """同一实体的一把排他锁。进程死掉时 flock 由内核释放，不会留死锁文件。"""
    lock_path = Path(entity_path) / ".items.lock"
    with open(lock_path, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_items(items_path):
    return json.loads(Path(items_path).read_text(encoding="utf-8"))


def write_items_atomic(items_path, data):
    """写 .tmp 再 rename：不会留下半截 JSON。"""
    items_path = Path(items_path)
    tmp_path = items_path.with_name(items_path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp_path, items_path)


def next_fact_id(entity_name, items):
    """在**已经读进来的**那份数据上算下一个 id，不再二次读盘。"""
    max_id = 0
    for item in items:
        if "id" in item:
            try:
                num = int(str(item["id"]).split("-")[-1])
                max_id = max(max_id, num)
            except (ValueError, IndexError):
                pass
    return f"{entity_name}-{max_id + 1:03d}"


def prepare_fact(items, entity_name, fact_data):
    """校验 + 补默认值 + 分配 id，全部在内存里完成。"""
    missing = [f for f in REQUIRED_FIELDS if f not in fact_data]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    if "id" not in fact_data:
        fact_data["id"] = next_fact_id(entity_name, items)

    fact_data.setdefault("status", "active")
    fact_data.setdefault("supersededBy", None)
    fact_data.setdefault("relatedEntities", [])
    fact_data.setdefault("lastAccessed", datetime.now().strftime("%Y-%m-%d"))
    fact_data.setdefault("accessCount", 0)
    return fact_data


def add_fact(entity_path, fact_data):
    """Add a new fact to items.json."""
    items_path = Path(entity_path) / "items.json"
    if not items_path.exists():
        print(f"Error: items.json not found at {items_path}")
        sys.exit(1)

    entity_name = Path(entity_path).name
    with entity_lock(entity_path):
        data = load_items(items_path)
        try:
            fact = prepare_fact(data["items"], entity_name, dict(fact_data))
        except ValueError as exc:
            print(f"Error: {exc}")
            sys.exit(1)

        data["items"].append(fact)
        data["lastModified"] = datetime.now().isoformat()
        write_items_atomic(items_path, data)

    print(f"✓ Added fact: {fact['id']}")
    return fact["id"]


def supersede_fact(entity_path, old_fact_id, new_fact_data):
    """Mark a fact as superseded and add a new one — 一次落盘，全成或全不成。"""
    items_path = Path(entity_path) / "items.json"
    if not items_path.exists():
        print(f"Error: items.json not found at {items_path}")
        sys.exit(1)

    entity_name = Path(entity_path).name
    with entity_lock(entity_path):
        data = load_items(items_path)

        old_fact = next(
            (it for it in data["items"] if it.get("id") == old_fact_id), None
        )
        if old_fact is None:
            print(f"Error: Fact {old_fact_id} not found")
            sys.exit(1)

        try:
            new_fact = prepare_fact(data["items"], entity_name, dict(new_fact_data))
        except ValueError as exc:
            print(f"Error: {exc}")
            sys.exit(1)

        # 三处改动在内存里一次算完，只写一次盘
        data["items"].append(new_fact)
        old_fact["status"] = "superseded"
        old_fact["supersededBy"] = new_fact["id"]
        data["lastModified"] = datetime.now().isoformat()
        write_items_atomic(items_path, data)

    print(f"✓ Added fact: {new_fact['id']}")
    print(f"✓ Superseded fact: {old_fact_id} → {new_fact['id']}")
    return new_fact["id"]


def main():
    parser = argparse.ArgumentParser(description="Add or update facts in entity")
    parser.add_argument("entity_path", help="Path to entity directory")
    parser.add_argument("--add", help="Add new fact (JSON string)")
    parser.add_argument("--supersede", nargs=2, metavar=("OLD_ID", "NEW_FACT"),
                        help="Supersede old fact with new one")

    args = parser.parse_args()

    if args.add:
        fact_data = json.loads(args.add)
        add_fact(args.entity_path, fact_data)
    elif args.supersede:
        old_id, new_fact_json = args.supersede
        new_fact_data = json.loads(new_fact_json)
        supersede_fact(args.entity_path, old_id, new_fact_data)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
