"""UI 표시·탐색 회귀 시험. DB·.env·서버 모듈을 읽지 않는다."""
import ast
import html
import json
import re
import unittest
from pathlib import Path

import structure_svg

HERE = Path(__file__).parent
HTML = (HERE / "app.html").read_text()   # 정적 뼈대(인라인 스크립트·스타일 0) — 화면·라우터는 React(server/ui), CSS 는 번들(tokens.css·global.css)
UI = HERE / "ui" / "src"
CSS = (UI / "shared" / "tokens.css").read_text(encoding="utf-8") + (UI / "shared" / "global.css").read_text(encoding="utf-8")


class UIAlignmentTest(unittest.TestCase):
    def test_type_labels_keep_origins_and_protection(self):
        # 칩 글자 = 서버 ORIGIN_TEXT(/api/state origin_labels) — React shared/origin.tsx 가 그대로 쓴다(Vitest DefsScreen·ObjectsScreen)
        self.assertEqual([structure_svg.ORIGIN_TEXT[k] for k in ("core", "standard", "template", "custom")], ["표준", "표준", "커스텀", "커스텀"])
        fixture = {"objects": [{"id": "o1", "label": "샘플", "origin": "standard", "locked": True, "fields": []}],
                   "core": [{"kind": "record"}], "relations": []}
        before = json.dumps(fixture, ensure_ascii=False)
        svg = structure_svg.render(fixture)
        self.assertNotIn("코어", svg)
        self.assertIn("표준 정의 보호", svg)
        self.assertEqual(before, json.dumps(fixture, ensure_ascii=False))

    def test_single_settings_entry_for_all_roles(self):
        """설정 = 모든 역할에서 톱니 하나(탭 줄에 없음). Setup 페이지 줄·관리자 운영 링크는 Vitest layout/App.test.tsx · shared/route.test.ts."""
        gear = re.search(r'<a[^>]+id="setup-link"[^>]*>.*?</a>', HTML).group()
        self.assertIn('href="#_setup"', gear)
        self.assertIn('aria-label="설정"', gear)
        self.assertNotIn(' hidden', gear)

    def test_official_font_with_swap_and_system_fallback(self):
        self.assertRegex(HTML, r'https://fonts.googleapis.com/css2\?family=Noto\+Sans\+KR[^" ]*display=swap')
        self.assertRegex(CSS, r'font: 14px/1.55 "Noto Sans KR", -apple-system, "Apple SD Gothic Neo", sans-serif')
        self.assertIn('referrerpolicy="no-referrer"', HTML)

    def test_account_settings_do_not_duplicate_gear(self):
        """설정 하위 화면은 톱니 하나에서만 — 계정 메뉴의 「내 구조 설정」·「연결 장치」는 늘 숨김(화면 코드가 켜지 않는다).
        톱니 주소(관리자 이름 관문 = /admin/setup, 그 밖 #_setup)는 Vitest layout/App.test.tsx."""
        for i in ("acct-settings", "acct-devices"):
            tag = re.search(rf'<button[^>]+id="{i}"[^>]*>', HTML)
            self.assertTrue(tag and re.search(r"\shidden(\s|>)", tag.group()), i)
        src = "".join(p.read_text(encoding="utf-8") for p in UI.rglob("*.ts*") if ".test." not in p.name)
        self.assertNotIn("acct-settings", src)
        self.assertNotIn("acct-devices", src)
        console = re.search(r'<a[^>]+id="acct-console"[^>]*>', HTML)
        self.assertTrue(console is None or ' hidden' in console.group())

    def test_one_origin_definition_for_app_and_graph(self):
        """출처 표시 정의는 서버 하나(structure_svg) — /api/state origin_labels 로 내려 주고, 화면(app.html·React)엔 사본·자리표가 없다(R5b-1)."""
        web = (HERE / "web.py").read_text(encoding="utf-8")
        self.assertIn('st["origin_labels"] = {"text": structure_svg.ORIGIN_TEXT, "category": structure_svg.ORIGIN_CATEGORY}', web)
        self.assertNotIn("fill_origin_labels(", web)
        self.assertNotIn("{{origin-text}}", HTML)
        self.assertNotIn("ORIGIN_TEXT", HTML)
        src = "".join(p.read_text(encoding="utf-8") for p in UI.rglob("*.ts*") if ".test." not in p.name)
        self.assertNotIn("ORIGIN_CHIP", src)
        self.assertIn("S.origin_labels", (UI / "shared" / "origin.tsx").read_text(encoding="utf-8"))
        self.assertNotIn('"코어"', src)

    def test_standard_confirmation_uses_material_type_terms(self):
        code = [l for l in (UI / "features" / "defs" / "text.ts").read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("//")]
        self.assertTrue(code and not [l for l in code if '오브젝트' in l])

    def test_lock_accessible_names_use_standard_category(self):
        self.assertFalse('aria-label="기본"' in HTML)
        self.assertFalse('title="기본"' in HTML)

    def test_admin_legend_matches_graph_categories(self):
        tree = ast.parse((HERE / "web.py").read_text())
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_om_legend')
        ns = {"structure_svg": structure_svg, "_esc": html.escape}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'web.py', 'exec'), ns)
        legend = ns['_om_legend']()
        self.assertEqual(legend.count('>표준</span>'), 1)
        self.assertNotIn('o-core', legend)
        self.assertIn('o-standard', legend)
        legend = ns['_om_legend'](('core', 'standard', 'template', 'custom'))
        self.assertEqual(legend.count('>표준</span>'), 1)
        self.assertEqual(legend.count('>커스텀</span>'), 1)

    def test_legend_and_list_use_two_categories(self):
        self.assertEqual(structure_svg.legend_origins(), ("standard", "template"))
        # 자료 종류 색인은 React(features/objects, R4-2) — 묶음 이름 표준 + 자물쇠 아이콘 · 카드 칩 = 서버 origin_labels(shared/origin.tsx, 손 사본 없음 R5b-1)
        index = (UI / "features" / "objects" / "Index.tsx").read_text(encoding="utf-8")
        self.assertIn('<Lock label="표준 정의 보호" />', index)
        self.assertNotIn("기본 🔒", index)
        self.assertIn("originChip(S, c.oc)", index)

    def test_body_bold_renders_safely(self):
        """사용자 글 본문의 **굵게** 는 <strong>, 그 밖은 글자 그대로 — 화면은 전부 React(shared/rich.tsx·Para.tsx, 사례 rich.cases.json = Vitest rich.test.tsx).
        app.html 은 정적 뼈대 — 인라인 스크립트가 없어 사용자 본문을 HTML 로 꽂는 자리가 없다(innerHTML 0 = arch.test.ts)."""
        self.assertIsNone(re.search(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", HTML, re.I))


if __name__ == '__main__':
    unittest.main()
