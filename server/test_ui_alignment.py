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
HTML = structure_svg.fill_origin_labels((HERE / "app.html").read_text())
JS = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)


def js_run(code):
    result = subprocess.run(["node", "-e", code], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class UIAlignmentTest(unittest.TestCase):
    def test_type_labels_keep_origins_and_protection(self):
        chips = JS[JS.index("const ORIGIN_TEXT"):JS.index("const VTYPE")]
        result = js_run('const esc = x => x, NT = x => x;\n' + chips +
                        '\nconsole.log(JSON.stringify(["core","standard","template","custom"].map(originChip)));')
        self.assertEqual([re.sub('<[^>]+>', '', x) for x in result], ["표준", "표준", "커스텀", "커스텀"])
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

    def test_one_origin_definition_for_app_and_graph(self):
        self.assertTrue(hasattr(structure_svg, 'fill_origin_labels'))
        rendered = structure_svg.fill_origin_labels(HTML)
        self.assertNotIn('/*{{origin-text}}*/ {}', rendered)
        labels = re.search(r'const ORIGIN_TEXT = (.*?);', rendered).group(1)
        self.assertEqual(json.loads(labels), structure_svg.ORIGIN_TEXT)
        self.assertNotIn('"코어"', rendered)

    def test_standard_confirmation_uses_material_type_terms(self):
        confirmation = JS[JS.index("const STRUCT_TEXT"):JS.index("async function stdChoose(")]
        self.assertNotIn('오브젝트', confirmation)

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
        # 자료 종류 색인은 React(features/objects, R4-2) — 묶음 이름 표준 🔒 · 카드 칩 = structure_svg 범주(손 사본 대조)
        objs = HERE / "ui" / "src" / "features" / "objects"
        index = (objs / "Index.tsx").read_text(encoding="utf-8")
        self.assertIn('title="표준 🔒"', index)
        self.assertNotIn("기본 🔒", index)
        chip = re.search(r"export const ORIGIN_CHIP[^=]*= (\{.*?\});", (objs / "text.ts").read_text(encoding="utf-8")).group(1)
        chip = json.loads(re.sub(r"(\w+):", r'"\1":', chip))
        self.assertEqual({k: v[1] for k, v in chip.items()}, structure_svg.ORIGIN_TEXT)
        self.assertEqual({k: v[0] == "o-std" for k, v in chip.items()}, {k: c == "standard" for k, c in structure_svg.ORIGIN_CATEGORY.items()})

    def test_body_bold_renders_safely(self):
        """사용자 글 본문의 **굵게** 는 <strong>, 그 밖은 escape. 홀수·빈 ** 는 그대로, 인용 mark 안에서도 짝이 맞는다.
        사례 = ui/src/shared/rich.cases.json — 새 TS(rich.test.tsx)가 같은 사례를 통과한다. 옛 rich·paraHtml 은 R5 까지 일시 중복(migrated.json)."""
        cases = json.loads((HERE / "ui" / "src" / "shared" / "rich.cases.json").read_text(encoding="utf-8"))
        funcs = JS[JS.index("const esc ="):JS.index("const $ = id")] + JS[JS.index("function paraHtml"):JS.index("function attachHtml")]
        result = js_run(funcs + "\nconst C = " + json.dumps(cases, ensure_ascii=False) + ";\n" +
                        "console.log(JSON.stringify({rich: C.rich.map(c => rich(c.in)), para: C.para.map(c => paraHtml(c.in, c.quote))}));")

        def esc(t):
            return html.escape(t, quote=True).replace("&#x27;", "&#39;")

        def want(out):
            return "".join(f"<{tag}>{esc(t)}</{tag}>" if tag else esc(t) for tag, t in out)
        self.assertEqual(len(result["rich"]), len(cases["rich"]))
        for c, got in zip(cases["rich"], result["rich"]):
            self.assertEqual(got, want(c["out"]), c["in"])
            self.assertNotIn("<img", got)
        for c, got in zip(cases["para"], result["para"]):
            self.assertEqual(got, f'<p class="{"h" if c["h"] else ""}">{want(c["out"])}</p>', c["in"])
        self.assertNotIn("${esc(x.body)}", JS.replace('esc(x.body) : ""', ""))
        self.assertNotIn("${esc(cur.body)}", JS)


if __name__ == '__main__':
    unittest.main()
