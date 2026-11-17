#!/usr/bin/env python3
"""Export the static WordPress snapshot as separately usable page folders."""
from __future__ import annotations

import argparse
import os
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
SITE = 'https://www.hellolead.pro/'
PAGES = [Path('index.html')] + sorted(p for p in ROOT.glob('*/index.html') if p.parts[-2] not in {'wp-content', 'wp-includes', 'xor'}) + sorted(ROOT.glob('author/*/index.html')) + sorted(ROOT.glob('category/*/index.html'))
PAGES = [p.relative_to(ROOT) if p.is_absolute() else p for p in PAGES]

CSS = '''/* Local static-export form notice. */
.local-form-notice { padding: 12px 16px; margin: 12px 0; border: 1px solid #d8e6f9; border-radius: 6px; background: #f1f7fd; color: #23334a; font: 14px/1.5 Arial, sans-serif; }
'''
JS = '''// This is a static export: do not submit personal data to a missing WordPress backend.
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('form').forEach(function (form) {
    var message = document.createElement('p');
    message.className = 'local-form-notice';
    message.setAttribute('role', 'status');
    message.textContent = 'Ce formulaire ne peut pas être envoyé depuis cette copie statique. Un service de réception doit être configuré.';
    form.insertAdjacentElement('beforebegin', message);
  });
});
document.addEventListener('submit', function (event) {
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);
'''
README = '''PAGE HELLOLEAD — EXPORT AUTONOME

Chaque dossier contient son index.html et ses propres ressources locales.
Pour l'ouvrir, lancez un serveur depuis le dossier de cette page :
  python3 -m http.server 8000
Sous Windows : py -m http.server 8000
Puis ouvrez http://localhost:8000/.

Les liens vers les autres pages Hellolead ouvrent le site en ligne, afin que
ce dossier reste utilisable séparément. Les services externes (polices Google,
liens partenaires, suivi et intégrations) peuvent nécessiter Internet.
Le reCAPTCHA a été retiré de cette copie statique uniquement. Les formulaires
ne sont pas envoyés : ils nécessitent un serveur ou un service de réception,
et une protection anti-spam adaptée en production. Aucun message de succès
n'est simulé. Le site WordPress d'origine n'est pas modifié par cet export.
Consultez RESSOURCES-MANQUANTES.txt pour les fichiers absents du dépôt source.
'''

class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ('src', 'poster'):
            if attrs.get(name):
                self.urls.append(attrs[name])
        if tag in ('link', 'image') and attrs.get('href'):
            self.urls.append(attrs['href'])
        for ref in attrs.get('srcset', '').split(','):
            if ref.strip():
                self.urls.append(ref.strip().split()[0])


def remove_remote_forms_and_captcha(html):
    def strip_script(match):
        text = match.group(0)
        if re.search(r'recaptcha|grecaptcha|id=["\'](?:contact-form-7-js(?:-[^"\']*)?|swv-js)["\']', text, re.I):
            return ''
        return text
    return re.sub(r'<script\b[^>]*>[\s\S]*?</script\s*>', strip_script, html, flags=re.I)


def rewrite_assets(html):
    # Escaped slashes are used in Elementor's JSON configuration.
    for slash, prefix_vendor, prefix_img in [(r'\/', r'.\/vendor\/', r'.\/img\/'), ('/', './vendor/', './img/')]:
        sep = re.escape(slash)
        lead = rf'(?:(?:\.\.?){sep})+'
        for original, target in [('wp-content/uploads/premium-addons-elementor/', prefix_vendor), ('wp-content/uploads/', prefix_img), ('wp-content/', prefix_vendor), ('wp-includes/', prefix_vendor)]:
            pattern = lead + sep.join(re.escape(x) for x in original.rstrip('/').split('/')) + sep
            replacement = target + original.replace('/', slash)
            html = re.sub(pattern, lambda m, r=replacement: r, html)
    return html


def rewrite_navigation(html, source):
    base = urljoin(SITE, source.parent.as_posix().strip('.') + ('/' if source.parent != Path('.') else ''))
    def change(match):
        before, quote, value = match.groups()
        parsed = urlsplit(value)
        if not value or value.startswith('#') or parsed.scheme or parsed.netloc:
            return match.group(0)
        # Relative page links become live links; static resource links are untouched.
        if parsed.path.endswith('index.html') or parsed.path.startswith('/'):
            target = urljoin(base, value)
            parts = urlsplit(target)
            if parts.path.endswith('/index.html'):
                target = urlunsplit((parts.scheme, parts.netloc, parts.path[:-10], parts.query, parts.fragment))
            if source.parent == Path('.') and value == './index.html':
                target = './index.html'
            return before + quote + target + quote
        return match.group(0)
    return re.sub(r'(<a\b[^>]*?\bhref\s*=\s*)(["\'])(.*?)(?:\2)', change, html, flags=re.I | re.S)


def resolve_relative(ref, base):
    """Resolve CSS URLs, including a broken premium-addons font path in the source."""
    src = (ROOT / base / unquote(urlsplit(ref).path)).resolve()
    marker = 'plugins/premium-addons-for-elementor/assets/editor/fonts/'
    path = unquote(urlsplit(ref).path)
    if not src.is_file() and marker in path:
        src = (ROOT / 'wp-content' / path[path.index(marker):]).resolve()
    return src


def add_ref(ref, page, files, missing, base=None):
    u = urlsplit(ref.strip())
    if u.scheme or u.netloc or not u.path or u.path.startswith('/') or u.path.startswith('#'):
        return
    parent = base if base is not None else page.parent
    src = resolve_relative(ref, parent)
    try:
        rel = src.relative_to(ROOT)
    except ValueError:
        return
    if not str(rel).startswith(('wp-content/', 'wp-includes/')):
        return
    if src.is_file():
        files.add(rel)
    else:
        missing.add(rel.as_posix())


def dest_for(path):
    path = path.as_posix()
    if path.startswith('wp-content/uploads/') and not path.startswith('wp-content/uploads/premium-addons-elementor/'):
        return Path('img') / path
    return Path('vendor') / path


def collect(source, html):
    refs = References()
    refs.feed(html)
    refs.urls.extend(re.findall(r'url\(\s*["\']?([^\)"\']+)', html, re.I))
    files, missing = set(), set()
    for ref in refs.urls:
        add_ref(ref, source, files, missing)
    # Elementor/Pro resolve widget chunks dynamically from the runtime's own URL.
    for plugin in ('elementor', 'elementor-pro'):
        directory = ROOT / 'wp-content' / 'plugins' / plugin / 'assets' / 'js'
        for path in directory.glob('*.bundle.min.js'):
            files.add(path.relative_to(ROOT))
    emoji = Path('wp-includes/js/wp-emoji-release.min.js')
    if (ROOT / emoji).is_file():
        files.add(emoji)
    # Resolve CSS font files, imports and background images using their original base.
    checked = set()
    while True:
        pending = [f for f in files if f.suffix.lower() == '.css' and f not in checked]
        if not pending:
            break
        for path in pending:
            checked.add(path)
            content = (ROOT / path).read_text(encoding='utf-8', errors='replace')
            for ref in re.findall(r'url\(\s*["\']?([^\)"\']+)', content, re.I):
                # Assets referenced from a CSS file need their original relative layout.
                add_ref(ref, source, files, missing, path.parent)
    return files, missing


def export_one(source, out):
    raw = (ROOT / source).read_text(encoding='utf-8')
    clean = remove_remote_forms_and_captcha(raw)
    files, missing = collect(source, clean)
    html = rewrite_navigation(rewrite_assets(clean), source)
    insertion = '<link rel="stylesheet" href="./css/local.css">\n<script src="./js/local.js"></script>\n'
    html = html.replace('</head>', insertion + '</head>', 1)
    out.mkdir(parents=True)
    for directory in ('css', 'js', 'img', 'vendor'):
        (out / directory).mkdir(exist_ok=True)
    for path in sorted(files):
        dest = out / dest_for(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == '.css':
            content = (ROOT / path).read_text(encoding='utf-8', errors='replace')
            def rewrite_css_url(match):
                ref = match.group(2).strip()
                url = urlsplit(ref)
                if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
                    return match.group(0)
                original = resolve_relative(ref, path.parent)
                try:
                    rel = original.relative_to(ROOT)
                except ValueError:
                    return match.group(0)
                if rel not in files:
                    return match.group(0)
                target = os.path.relpath(dest_for(rel), dest_for(path).parent).replace(os.sep, '/')
                if url.query:
                    target += '?' + url.query
                if url.fragment:
                    target += '#' + url.fragment
                return match.group(1) + target + match.group(3)
            content = re.sub(r'(url\(\s*["\']?)([^\)"\']+)(["\']?\s*\))', rewrite_css_url, content, flags=re.I)
            dest.write_text(content, encoding='utf-8')
        else:
            shutil.copyfile(ROOT / path, dest)
    (out / 'index.html').write_text(html, encoding='utf-8')
    (out / 'css/local.css').write_text(CSS, encoding='utf-8')
    (out / 'js/local.js').write_text(JS, encoding='utf-8')
    (out / 'LISEZ-MOI.txt').write_text(README, encoding='utf-8')
    (out / 'RESSOURCES-MANQUANTES.txt').write_text('\n'.join(sorted(missing)) + ('\n' if missing else 'Aucune ressource locale manquante détectée.\n'), encoding='utf-8')
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'exports-pages')
    parser.add_argument('--zip', type=Path, default=ROOT / 'pages-hellolead.zip')
    args = parser.parse_args()
    if args.output.exists() or args.zip.exists():
        parser.error('La sortie existe déjà ; choisissez un nouveau chemin pour ne rien écraser.')
    args.output.mkdir(parents=True)
    all_missing = {}
    for page in PAGES:
        name = 'accueil' if page == Path('index.html') else '-'.join(page.parent.parts)
        all_missing[name] = sorted(export_one(page, args.output / name))
        print(f'{name}: {len(all_missing[name])} ressource(s) manquante(s)')
    with ZipFile(args.zip, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(args.output.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(args.output))
    print(f'{len(PAGES)} pages exportées dans {args.zip}')

if __name__ == '__main__':
    main()
