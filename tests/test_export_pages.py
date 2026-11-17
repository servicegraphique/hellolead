import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

SPEC = importlib.util.spec_from_file_location('export_pages', Path(__file__).resolve().parents[1] / 'tools' / 'export_pages.py')
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)


class ExportTests(unittest.TestCase):
    def test_page_names_resolve_collisions(self):
        pages = [Path('index.html'), Path('accueil/index.html'), Path('accueil-2/index.html')]
        names = list(export.page_names(pages))
        self.assertEqual([name for _, name in names], ['accueil', 'accueil-2', 'accueil-2-2'])

    def test_export_every_page_without_recaptcha(self):
        with tempfile.TemporaryDirectory() as directory:
            for page in export.PAGES:
                out = Path(directory) / ('-'.join(page.parts))
                missing = export.export_one(page, out)
                html = (out / 'index.html').read_text(encoding='utf-8')
                scripts = re.findall(r'<script\b[^>]*>[\s\S]*?</script\s*>', html, re.I)
                self.assertFalse(any(re.search(r'recaptcha|grecaptcha', s, re.I) for s in scripts), page)
                for folder in ('css', 'js', 'img', 'vendor'):
                    self.assertTrue((out / folder).is_dir(), (page, folder))
                self.assertIn('preventDefault()', (out / 'js/local.js').read_text())
                refs = export.References()
                refs.feed(html)
                for ref in refs.urls:
                    u = urlsplit(ref)
                    if u.scheme or u.netloc or not u.path.startswith(('./vendor/', './img/', './css/', './js/')):
                        continue
                    actual = out / unquote(u.path)
                    if not actual.exists():
                        self.assertTrue(any(unquote(u.path).endswith(item) for item in missing), (page, ref))
                for css in out.rglob('*.css'):
                    content = css.read_text(encoding='utf-8', errors='replace')
                    for ref in re.findall(r'url\(\s*["\']?([^\)"\']+)', content, re.I):
                        u = urlsplit(ref)
                        if u.scheme or u.netloc or not u.path or u.path.startswith('/'):
                            continue
                        self.assertTrue((css.parent / unquote(u.path)).exists(), (page, css, ref))

    def test_navigation_and_json_asset_paths(self):
        html = '<a href="./../contact/index.html">Contact</a> "assets":".\\/..\\/wp-content\\/plugins\\/elementor\\/assets\\/"'
        result = export.rewrite_navigation(export.rewrite_assets(html), Path('parametre/index.html'))
        self.assertIn('https://www.hellolead.pro/contact/', result)
        self.assertIn('.\\/vendor\\/wp-content\\/plugins\\/elementor\\/assets\\/', result)

    def test_removes_typ_inline_captcha(self):
        text = (export.ROOT / 'typ/index.html').read_text(encoding='utf-8')
        result = export.remove_remote_forms_and_captcha(text)
        self.assertNotIn('google.com/recaptcha/api.js', result)
        self.assertNotIn("setAttribute('data-sitekey'", result)
        self.assertIn('class="elementor-form"', result)


if __name__ == '__main__':
    unittest.main()
