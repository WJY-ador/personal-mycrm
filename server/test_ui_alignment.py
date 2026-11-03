"""UI 표시·탐색 회귀 시험. DB·.env·서버 모듈을 읽지 않는다."""
import ast
import html
import json
import re
import subprocess
import unittest
from pathlib import Path

import structure_svg

HERE = Path(__file__).parent
HTML = (HERE / "app.html").read_text()
UI = HERE / "ui" / "src"
JS = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)


def js_run(code):
    result = subprocess.run(["node", "-e", code], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


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
        navigation = JS[JS.index("const BASE ="):JS.index("function tabCount(")]
        setup = JS[JS.index("const SETUP_PAGES"):JS.index("function renderSetup(")]
        result = js_run('const LABELS = {}, ok = () => true, esc = x => x, trashOn = () => false;\n'
                        'let S;\n' + navigation + '\n' + setup + '\n' + '''
const out = [];
for (const admin of [false, true]) {
  S = {user: {admin}, tabs: []};
  out.push({admin, tabs: tabsList().map(t => t.id), view: pickTab({tab: "_setup"}, tabsList()).view,
    subnav: setupNav("layout")});
}
console.log(JSON.stringify(out));
''')
        for row in result:
            self.assertEqual(row['view'], 'setup', row)
            self.assertNotIn('_setup', row['tabs'], row)
            self.assertEqual('/admin/setup' in row['subnav'], row['admin'], row)
            self.assertEqual('/admin"' in row['subnav'], row['admin'], row)
            for slug in ('layout', 'structure', 'objects', 'devices', 'map', 'help'):
                self.assertIn('#_setup/' + slug, row['subnav'])
        gear = re.search(r'<a[^>]+id="setup-link"[^>]*>.*?</a>', HTML).group()
        self.assertIn('href="#_setup"', gear)
        self.assertIn('aria-label="설정"', gear)
        self.assertNotIn(' hidden', gear)
        self.assertNotIn('$("setup-link").hidden', JS)

    def test_official_font_with_swap_and_system_fallback(self):
        self.assertRegex(HTML, r'https://fonts.googleapis.com/css2\?family=Noto\+Sans\+KR[^" ]*display=swap')
        self.assertRegex(HTML, r'font: 14px/1.55 "Noto Sans KR", -apple-system, "Apple SD Gothic Neo", sans-serif')
        self.assertIn('referrerpolicy="no-referrer"', HTML)

    def test_account_settings_do_not_duplicate_gear(self):
        account = JS[JS.index("function acctApply()"):JS.index("function acctClose()")]
        result = js_run("""
const out = [], document = {querySelectorAll: () => []};
let S, nodes, gate;
const $ = id => nodes[id], needName = () => gate;
""" + account + """
for (const admin of [false, true]) for (gate of [false, true]) {
  S = {user: {admin, display_name: gate ? "" : "합성 사용자"}};
  nodes = new Proxy({}, {get: (obj, key) => obj[key] ||= {hidden: true, href: "#_setup",
    classList: {toggle() {}}, setAttribute() {}}});
  acctApply();
  out.push({admin, gate, settings: nodes["acct-settings"].hidden, devices: nodes["acct-devices"].hidden, gear: nodes["setup-link"].href});
}
console.log(JSON.stringify(out));
""")
        for row in result:
            self.assertTrue(row['settings'], row)
            self.assertTrue(row['devices'], row)
            self.assertEqual(row['gear'], '/admin/setup' if row['gate'] and row['admin'] else '#_setup', row)
        console = re.search(r'<a[^>]+id="acct-console"[^>]*>', HTML)
        self.assertTrue(console is None or ' hidden' in console.group())

    def test_old_links_keep_review_routes(self):
        """옛 묶음 주소 replace — 지도·오늘의 대조 링크(#map/review/…·#today/review/…)는 판단 검토로 그대로(R5a)."""
        replace = JS[JS.index("function navReplace(R)"):JS.index("const setupPages")]
        result = js_run('const defById = () => null, itemById = () => null, meTabOfItem = () => "";\n' + replace + """
const R = (tab, a = "", b = "") => ({tab, a, b, c: "", d: ""});
console.log(JSON.stringify([R("map"), R("map", "review", "q1"), R("today"), R("today", "x"), R("today", "review", "q1"), R("home", "review", "r:r1")].map(navReplace)));
""")
        self.assertEqual(result, ["#_setup/map", "", "#_today", "#_today", "", ""])

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
        self.assertNotIn('오브젝트', (UI / "features" / "defs" / "text.ts").read_text(encoding="utf-8").split("\n", 2)[2])

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
        # 자료 종류 색인은 React(features/objects, R4-2) — 묶음 이름 표준 🔒 · 카드 칩 = 서버 origin_labels(shared/origin.tsx, 손 사본 없음 R5b-1)
        index = (UI / "features" / "objects" / "Index.tsx").read_text(encoding="utf-8")
        self.assertIn('title="표준 🔒"', index)
        self.assertNotIn("기본 🔒", index)
        self.assertIn("originChip(S, c.oc)", index)

    def test_body_bold_renders_safely(self):
        """사용자 글 본문의 **굵게** 는 <strong>, 그 밖은 글자 그대로 — 화면은 전부 React(shared/rich.tsx·Para.tsx, 사례 rich.cases.json = Vitest rich.test.tsx).
        옛 app.html 의 rich·paraHtml 은 R5b-1 에서 지웠다. 남은 옛 쪽엔 사용자 본문을 HTML 로 꽂는 자리가 없다."""
        self.assertNotIn("const rich =", JS)
        self.assertNotIn("${esc(x.body)}", JS.replace('esc(x.body) : ""', ""))
        self.assertNotIn("${esc(cur.body)}", JS)


if __name__ == '__main__':
    unittest.main()
