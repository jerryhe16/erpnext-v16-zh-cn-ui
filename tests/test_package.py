from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PackageTests(unittest.TestCase):
    def test_current_client_sources_have_zh_overrides(self):
        from install import translations

        rows = translations(ROOT / "translations.csv")
        self.assertEqual(rows[("Item", "")], "物料")
        self.assertEqual(rows[("All apps", "")], "返回桌面")
        self.assertEqual(rows[("{0} of {1} done · {2} skipped", "")], "已完成 {0}/{1} 项 · 已跳过 {2} 项")
        self.assertNotIn(("Add Item", ""), rows)

    def test_preserves_existing_site_translations_and_is_idempotent(self):
        from install import translation_changes

        requested = {("Item", ""): "物料", ("All apps", ""): "返回桌面"}
        installed = {("Item", ""): "商品", ("All apps", ""): "返回桌面"}
        additions, conflicts = translation_changes(requested, installed)
        self.assertEqual(additions, {})
        self.assertEqual(conflicts, [("Item", "")])

    def test_icons_cover_each_desktop_function_and_use_local_svg(self):
        from install import icons

        entries = icons(ROOT)
        self.assertEqual(len(entries), 13)
        self.assertEqual(entries["Item"]["group"], entries["Stock"]["group"])
        self.assertNotEqual(entries["Stock"]["group"], entries["Accounting"]["group"])
        self.assertTrue(all((ROOT / "icons" / e["file"]).is_file() for e in entries.values()))


if __name__ == "__main__":
    unittest.main()
