"""Builds the light theme for every PolarisAI page and keeps the theme switch in place.

The dark theme is the original design and stays the default. The light theme is generated from it:
every colour in each page's own CSS is mapped to a light, professional palette, by what the colour
does (text, background, border, shadow, chart line), and written as rules under
:root[data-ptheme="light"]. Hand-written adjustments live in tools/theme/light-<page>.css and are
added after the generated rules. Colours set in SVG attributes or inline styles are mapped the same
way. Anything inside an element with class "keep-dark" (the explainer video) is left as it is.

Run it again after changing a page's CSS:   python3 tools/theme_light.py site
It rewrites only the blocks between the THEME markers, so it is safe to run repeatedly.
"""
import colorsys, os, re, sys

SITE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..'))
HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = ['index.html', 'app.html', 'browser.html', 'data-status.html']
L = ':root[data-ptheme="light"]'
SKIP = ':where(:not(.keep-dark,.keep-dark *))'

# ---------- colour helpers ----------
NAMED = {'white': (255, 255, 255, 1), 'black': (0, 0, 0, 1)}
COLOR_RE = re.compile(r'#[0-9A-Fa-f]{8}\b|#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3,4}\b|rgba?\([^)]*\)|\b(?:white|black)\b')


def parse(c):
    c = c.strip()
    if c.lower() in NAMED: return NAMED[c.lower()]
    if c.startswith('#'):
        h = c[1:]
        if len(h) in (3, 4): h = ''.join(x * 2 for x in h)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)
    nums = [x.strip() for x in re.split(r'[,\s/]+', c[c.index('(') + 1:-1]) if x.strip()]
    r, g, b = [float(x[:-1]) * 2.55 if x.endswith('%') else float(x) for x in nums[:3]]
    a = float(nums[3][:-1]) / 100 if len(nums) > 3 and nums[3].endswith('%') else float(nums[3]) if len(nums) > 3 else 1
    return (r, g, b, a)


def fmt(r, g, b, a=1):
    r, g, b = [max(0, min(255, round(x))) for x in (r, g, b)]
    if a >= 0.999: return '#%02X%02X%02X' % (r, g, b)
    return 'rgba(%d,%d,%d,%s)' % (r, g, b, ('%.3f' % max(0, a)).rstrip('0').rstrip('.') or '0')


def lum(r, g, b):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(c1, c2=(255, 255, 255)):
    a, b = lum(*c1[:3]), lum(*c2[:3])
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def hls(c): return colorsys.rgb_to_hls(c[0] / 255, c[1] / 255, c[2] / 255)


def from_hls(h, l, s, a=1):
    r, g, b = colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))
    return (r * 255, g * 255, b * 255, a)


NAVY_H = 225 / 360
INK = (22, 33, 62)


def darken_to(c, target, bg=(255, 255, 255)):
    """Same hue, darker, until it reaches the contrast target against the light background."""
    h, l, s = hls(c)
    s = min(0.74, s)                          # calmer than the neon dark-theme accents
    for _ in range(80):
        x = from_hls(h, l, s, 1)
        if contrast(x, bg) >= target: return x
        l -= 0.01
    return from_hls(h, l, s, 1)


def neutral(c):
    h, l, s = hls(c)
    return s < 0.32 or l > 0.86


def m_text(c):
    r, g, b, a = c
    h, l, s = hls(c)
    if l < 0.35: return c                      # already dark text (sits on a light chip): keep
    if neutral(c):                             # white and pale blue text -> navy ink scale
        t = (1 - l) / 0.4                      # 0 for white, ~1 for mid grey
        nl = 0.16 + min(1, t) * 0.26
        hue = h if s > 0.15 else NAVY_H
        return from_hls(hue, nl, 0.42 if s > 0.05 else 0.38, a)
    x = darken_to(c, 5.6)                      # coloured text: same hue, readable on white and on tinted panels
    return (x[0], x[1], x[2], a)


def m_bg(c, prop=''):
    r, g, b, a = c
    h, l, s = hls(c)
    if l > 0.93 and a > 0.9: return c          # already white/pale fills (pills): keep
    if a < 0.6:
        if l > 0.8 and s < 0.5:                # translucent white lift -> faint navy tint
            return (INK[0], INK[1], INK[2], a * 0.42)
        if l < 0.3:                            # translucent dark panel -> light panel
            return (240, 244, 250, min(1, 0.55 + a))
        if neutral(c) or 190 <= h * 360 <= 240:
            return (47, 93, 194, a * 0.6)      # translucent pale blue -> soft blue tint
        return (r, g, b, min(1, a * 1.15))     # translucent accents (amber, green): keep, a bit stronger
    if l < 0.42:                               # dark surfaces -> white with a hint of blue
        nl = 0.985 - max(0, l - 0.08) * 0.12
        return from_hls(NAVY_H, nl, 0.45, a)
    return c                                   # saturated fills (buttons, chips, swatches): keep


def m_border(c):
    r, g, b, a = c
    h, l, s = hls(c)
    if a < 0.6:
        if l < 0.3: return (INK[0], INK[1], INK[2], 0.10)
        if neutral(c) or 190 <= h * 360 <= 240: return (INK[0], INK[1], INK[2], min(0.30, 0.08 + a * 0.35))
        return (*darken_to(c, 2.2)[:3], min(1, a + 0.25))
    if l < 0.35: return (255, 255, 255, a)       # dark rings (separators on dark) -> white
    if neutral(c): return (203, 213, 230, a)
    x = darken_to(c, 3.0)
    return (x[0], x[1], x[2], a)


def m_shadow(c):
    r, g, b, a = c
    h, l, s = hls(c)
    if l < 0.3: return (16, 24, 40, min(0.18, a * 0.35))
    if neutral(c) and l > 0.85: return (16, 24, 40, a * 0.25)
    return (*darken_to(c, 2.5)[:3], a * 0.6)


def m_fill(c):
    r, g, b, a = c
    h, l, s = hls(c)
    if a < 0.6: return m_bg(c)
    if l < 0.35: return m_bg(c)
    if neutral(c): return m_text(c)
    return darken_to(c, 3.0)


def m_stroke(c):
    r, g, b, a = c
    h, l, s = hls(c)
    if a < 0.6: return m_bg(c) if l < 0.3 else m_border(c) if neutral(c) or 190 <= h * 360 <= 240 else (*darken_to(c, 2.4)[:3], min(1, a + 0.2))
    if l < 0.35: return (255, 255, 255, a)
    if neutral(c): return (86, 98, 125, a)
    return darken_to(c, 3.4)


def category(prop):
    p = prop.lower()
    if p in ('color', '-webkit-text-fill-color', 'caret-color', 'text-decoration-color', 'text-decoration', 'column-rule-color'): return m_text
    if p.startswith('background'): return m_bg
    if p.startswith('border') or p.startswith('outline'): return m_border
    if p in ('box-shadow', 'text-shadow', 'filter'): return m_shadow
    if p in ('fill', 'stop-color', 'flood-color'): return m_fill
    if p == 'stroke': return m_stroke
    if p == 'accent-color': return lambda c: darken_to(c, 3.0)
    return None


def map_value(prop, val):
    fn = category(prop)
    if not fn: return None
    out, n = COLOR_RE.subn(lambda m: fmt(*fn(parse(m.group(0)))), val)
    return out if n and out != val else None


# ---------- a small CSS parser: rules, @media/@supports blocks; @keyframes are skipped ----------
def strip_comments(css): return re.sub(r'/\*[\s\S]*?\*/', '', css)


def parse_css(css):
    i, n, out = 0, len(css), []
    while i < n:
        j = css.find('{', i)
        if j < 0: break
        head = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == '{': depth += 1
            elif css[k] == '}': depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        semi = head.rfind(';')                 # stray @import/@charset before a rule
        if semi >= 0: head = head[semi + 1:].strip()
        if head.startswith('@media') or head.startswith('@supports'): out.append((head, parse_css(body)))
        elif head.startswith('@'): pass
        elif head: out.append((head, body))
        i = k
    return out


def split_decls(body):
    parts, cur, depth = [], '', 0
    for ch in body:
        if ch == '(': depth += 1
        elif ch == ')': depth -= 1
        if ch == ';' and depth == 0: parts.append(cur); cur = ''
        else: cur += ch
    if cur.strip(): parts.append(cur)
    return [p.strip() for p in parts if ':' in p]


def split_selectors(head):
    out, cur, depth = [], '', 0
    for ch in head:
        if ch in '([': depth += 1
        elif ch in ')]': depth -= 1
        if ch == ',' and depth == 0: out.append(cur.strip()); cur = ''
        else: cur += ch
    out.append(cur.strip())
    return [s for s in out if s]


PSEUDO_RE = re.compile(r'(::?(?:before|after|first-letter|first-line|placeholder|selection|marker|backdrop|-webkit-[a-z-]+|-moz-[a-z-]+))+$')


def scope(sel):
    """Light-theme version of a selector. Elements inside .keep-dark (the videos) keep the dark design."""
    if sel.startswith(':root'): return L + sel[5:]
    if re.match(r'html\b', sel): return 'html[data-ptheme="light"]' + sel[4:]
    if re.match(r'body\b', sel) and ' ' not in sel and '>' not in sel: return L + ' ' + sel
    m = PSEUDO_RE.search(sel)
    base, pseudo = (sel[:m.start()], sel[m.start():]) if m else (sel, '')
    return L + ' ' + base + ':where(:not(.keep-dark,.keep-dark *))' + pseudo


def gen_rules(rules, indent=''):
    out = []
    for head, body in rules:
        if isinstance(body, list):
            inner = gen_rules(body, indent + '  ')
            if inner: out.append(indent + head + '{\n' + '\n'.join(inner) + '\n' + indent + '}')
            continue
        decls = []
        for d in split_decls(body):
            prop, val = d.split(':', 1)
            prop = prop.strip()
            if prop.startswith('--'): continue   # tokens are set by hand in the fix file
            nv = map_value(prop, val.strip())
            if nv: decls.append(prop + ':' + nv)
        if decls:
            sels = split_selectors(head)
            out.append(indent + ','.join(scope(s) for s in sels) + '{' + ';'.join(decls) + '}')
    return out


# ---------- SVG attributes and inline styles written in the HTML or by scripts ----------
def m_text_fill(c):
    """SVG text drawn in a colour: same rule as HTML text."""
    return m_text(c)


def gen_attr_rules(src):
    """Scripts build charts with colours in attributes (fill="#8FB8FF") or inline styles
    (style="fill:'+c+'"), often from colour lists. Every colour written anywhere outside the CSS is
    mapped for each way it can be used, so dynamic colours are covered too. Mid-tone colours that
    already read well on white come out unchanged and produce no rule."""
    rules, seen = [], set()
    colours = []
    for m in COLOR_RE.finditer(src):
        v = m.group(0)
        if v.lower() in ('white', 'black') or v in colours: continue
        try: parse(v)
        except (ValueError, IndexError): continue     # built by a script at run time
        colours.append(v)

    def add(sel, prop, fn, imp=False):
        for v in colours:
            nv = fmt(*fn(parse(v)))
            if nv.replace(' ', '').upper() == v.replace(' ', '').upper(): continue
            key = (sel, v)
            if key in seen: continue
            seen.add(key)
            rules.append('%s %s%s{%s:%s%s}' % (L, sel.replace('V', v), SKIP, prop, nv, '!important' if imp else ''))
    add('[fill="V"]', 'fill', m_fill)
    add('text[fill="V"]', 'fill', m_text_fill)
    add('[stroke="V"]', 'stroke', m_stroke)
    add('[stop-color="V"]', 'stop-color', m_fill)
    add('[style*="fill:V"]', 'fill', m_fill, True)
    add('text[style*="fill:V"]', 'fill', m_text_fill, True)
    add('[style*="stroke:V"]', 'stroke', m_stroke, True)
    add('[style*="color:V"]', 'color', m_text, True)
    add('[style*="background:V"]', 'background', m_bg, True)
    add('[style*="background-color:V"]', 'background-color', m_bg, True)
    add('[style*="border-color:V"]', 'border-color', m_border, True)
    # compound inline values such as border:2px solid #FFFFFF
    for m in re.finditer(r'style=\\?["\']([^"\'\\]*)', src):
        for d in m.group(1).split(';'):
            if ':' not in d: continue
            prop, val = [x.strip() for x in d.split(':', 1)]
            if COLOR_RE.fullmatch(val) or not COLOR_RE.search(val) or (prop, val) in seen: continue
            seen.add((prop, val)); nv = map_value(prop, val)
            if nv: rules.append('%s [style*="%s:%s"]%s{%s:%s!important}' % (L, prop, val, SKIP, prop, nv))
    return rules


BOOT = ('<script id="theme-boot">/* THEME: before the page paints, use the theme this viewer chose last time (dark is the default) */'
        'try{if(localStorage.getItem("polaris-theme")==="light")document.documentElement.setAttribute("data-ptheme","light");}catch(e){}</script>')
TOGGLE = '''<script id="theme-toggle">/* THEME: the light/dark switch (every .theme-btn on the page) */
(function(){var root=document.documentElement;
  function cur(){return root.getAttribute('data-ptheme')==='light'?'light':'dark';}
  function sync(){var l=cur()==='light';[].forEach.call(document.querySelectorAll('.theme-btn'),function(b){b.setAttribute('aria-pressed',String(l));b.setAttribute('aria-label',l?'Switch to the dark theme':'Switch to the light theme');b.title=l?'Dark theme':'Light theme';var t=b.querySelector('.theme-lbl');if(t)t.textContent=l?'Dark':'Light';});
    var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute('content',l?'#F4F7FC':'#0B1E4D');}
  function set(t){if(t==='light')root.setAttribute('data-ptheme','light');else root.removeAttribute('data-ptheme');try{localStorage.setItem('polaris-theme',t);}catch(e){}sync();
    try{window.dispatchEvent(new CustomEvent('polaris:theme',{detail:t}));}catch(e){}}
  document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.theme-btn');if(b)set(cur()==='light'?'dark':'light');});
  window.addEventListener('storage',function(e){if(e.key==='polaris-theme'){if(e.newValue==='light')root.setAttribute('data-ptheme','light');else root.removeAttribute('data-ptheme');sync();}});
  sync();})();
</script>'''


def strip_scripts(s):
    return re.sub(r'<script\b[\s\S]*?</script>', '', s)


def page_css(s):
    s = re.sub(r'<style id="light-(?:auto|fix)">[\s\S]*?</style>', '', s)
    return '\n'.join(m.group(1) for m in re.finditer(r'<style[^>]*>([\s\S]*?)</style>', strip_scripts(s)))


def replace_block(s, start, end, new, anchor_before, last=False):
    """Swap the existing block for the new one, or insert it before the anchor. Scripts may contain
    '</body>' inside strings (the report file), so the closing anchor is searched from the end."""
    while start in s:
        i = s.index(start); j = s.index(end, i) + len(end)
        s = s[:i] + s[j:].lstrip('\n') if not s[i - 1:i] == '\n' else s[:i] + s[j:].lstrip('\n')
    k = s.rindex(anchor_before) if last else s.index(anchor_before)
    return s[:k] + new + '\n' + s[k:]


def build(page):
    path = os.path.join(SITE, page)
    s = open(path, encoding='utf-8').read()
    css = strip_comments(page_css(s))
    auto = gen_rules(parse_css(css))
    src = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', s)
    attrs = gen_attr_rules(src)
    fix_path = os.path.join(HERE, 'theme', 'light-' + page.replace('.html', '.css'))
    common = open(os.path.join(HERE, 'theme', 'light-common.css'), encoding='utf-8').read()
    fix = open(fix_path, encoding='utf-8').read() if os.path.exists(fix_path) else ''
    auto_block = ('<style id="light-auto">/* THEME: generated by tools/theme_light.py from this page\'s dark CSS. Do not edit by hand. */\n'
                  + '\n'.join(auto + attrs) + '\n</style>')
    fix_block = '<style id="light-fix">/* THEME: hand-written light-theme rules (tools/theme/light-common.css and light-' + page.replace('.html', '.css') + ') */\n' + common + '\n' + fix + '\n</style>'
    s = replace_block(s, '<script id="theme-boot">', '</script>', BOOT, '<title>')
    s = replace_block(s, '<style id="light-auto">', '</style>', auto_block, '</head>')
    s = replace_block(s, '<style id="light-fix">', '</style>', fix_block, '</head>')
    s = replace_block(s, '<script id="theme-toggle">', '</script>', TOGGLE, '</body>', last=True)
    open(path, 'w', encoding='utf-8').write(s)
    print('%-17s %4d generated rules, %3d attribute/inline rules, fix %5d bytes' % (page, len(auto), len(attrs), len(common) + len(fix)))


if __name__ == '__main__':
    for p in PAGES: build(p)
