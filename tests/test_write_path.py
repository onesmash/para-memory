#!/usr/bin/env python3
"""
S2/S3 守门测试：para-memory 写入路径的两条不变量。

对应 spec/ParaMemory.tla：
  P1 AtomicSupersede  —— supersede 必须一次落盘，崩溃不许留下「两个 active」
  P2 NoLostUpdate     —— 并发 --add 不许丢掉任何一次已打印成功的写入

这两条都是「坏了很贵、普通测试摸不到」：
  - 普通测试不会在两次写之间杀进程；
  - 普通测试不会让两个写者同时读到同一版文件。
本文件用「在写入口插入同步点」把窗口撑开，逻辑本身不动。

跑：python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "para-memory" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


update_entity = _load("update_entity")


class EntityFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pm-test-"))
        self.entity = self.root / "acme"
        self.entity.mkdir()
        self.items_path = self.entity / "items.json"
        self.items_path.write_text(json.dumps({
            "entity": "acme",
            "items": [{
                "id": "acme-001",
                "fact": "Series A closed at $8M",
                "category": "milestone",
                "timestamp": "2025-06-01",
                "source": "2025-06-01",
                "status": "active",
                "supersededBy": None,
            }],
            "lastModified": "2025-06-01T00:00:00",
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def read_items(self):
        return json.loads(self.items_path.read_text(encoding="utf-8"))["items"]

    def by_id(self, fid):
        for it in self.read_items():
            if it.get("id") == fid:
                return it
        return None


class TestSupersedeIsAtomic(EntityFixture):
    """P1：两次落盘之间崩溃，不许留下「新事实 active + 旧事实仍 active」。"""

    def test_crash_between_the_two_writes_leaves_no_partial_state(self):
        """在「写新事实」与「标记旧事实」之间注入崩溃，然后只看最终文件是不是全成或全不成。

        注入点：items.json* 的**第 2 次** write_text。
          - 两次写的实现：第 2 次写之前死掉 ⟹ 新事实已落盘、旧事实仍 active。
          - 一次原子写的实现：全程只有 1 次 write_text（写 .tmp 后 os.replace），
            注入点落空，操作要么完整完成、要么在 replace 之前死掉而文件不动。
        """
        real_write = Path.write_text
        calls = {"n": 0}
        crashed = {"yes": False}

        def dying_write(self, text, *a, **k):
            if self.name.startswith("items.json"):
                calls["n"] += 1
                if calls["n"] == 2:
                    crashed["yes"] = True
                    raise RuntimeError("simulated crash between the two writes")
            return real_write(self, text, *a, **k)

        new_fact = {
            "fact": "Series A closed at $12M, not $8M",
            "category": "milestone",
            "timestamp": "2025-06-14",
            "source": "2025-06-14",
        }

        with mock.patch.object(Path, "write_text", dying_write):
            try:
                update_entity.supersede_fact(str(self.entity), "acme-001", new_fact)
            except RuntimeError:
                pass

        items = self.read_items()
        old = self.by_id("acme-001")
        self.assertIsNotNone(old, "旧事实不见了——比半截 supersede 更糟")

        new_ids = [i["id"] for i in items if i["id"] != "acme-001"]
        partial = (len(new_ids) == 1
                   and old.get("status") == "active"
                   and not old.get("supersededBy"))

        self.assertFalse(
            partial,
            f"半截 supersede（crashed={crashed['yes']}）："
            f"新事实 {new_ids} 已落盘，旧事实仍是 active 且没有指针；"
            f"整份 items={[(i['id'], i.get('status'), i.get('supersededBy')) for i in items]}",
        )

        # 没有注入到崩溃时，操作必须**真的完成**——否则「什么都不做」也能让上面通过
        if not crashed["yes"]:
            self.assertEqual(
                old.get("status"), "superseded",
                f"操作没有真正生效（status={old.get('status')}）——空实现不许通过本测试",
            )
            self.assertIn(old.get("supersededBy"), [i["id"] for i in items],
                          "supersededBy 指向一个不存在的 id")


class TestConcurrentAddLosesNothing(EntityFixture):
    """P2：两个并发 --add，两条都必须留在最终文件里，且 id 不重复。"""

    def test_two_concurrent_adds_both_survive(self):
        real_write = Path.write_text
        barrier = threading.Barrier(2, timeout=1.0)
        errors = []

        def synced_write(self, text, *a, **k):
            # 两个写者都在「已经读完、还没写」的时刻对齐，把竞态窗口撑开；
            # 逻辑本身没有任何改动——真实运行时这个窗口只是窄得多。
            if self.name == "items.json":
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass
            return real_write(self, text, *a, **k)

        def add(tag):
            try:
                update_entity.add_fact(str(self.entity), {
                    "fact": f"concurrent fact {tag}",
                    "category": "note",
                    "timestamp": "2025-07-01",
                    "source": "2025-07-01",
                })
            except Exception as exc:  # noqa: BLE001
                errors.append((tag, repr(exc)))

        with mock.patch.object(Path, "write_text", synced_write):
            threads = [threading.Thread(target=add, args=(t,)) for t in ("A", "B")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        self.assertEqual(errors, [], f"并发写入抛错：{errors}")

        items = self.read_items()
        facts = [i["fact"] for i in items]
        ids = [i["id"] for i in items]

        self.assertIn("concurrent fact A", facts, f"写入 A 丢了；现有：{facts}")
        self.assertIn("concurrent fact B", facts, f"写入 B 丢了；现有：{facts}")
        self.assertEqual(
            len(ids), len(set(ids)),
            f"fact id 重复：{sorted(ids)}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
