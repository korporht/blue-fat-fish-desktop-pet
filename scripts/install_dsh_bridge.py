"""Add a marked, removable bridge row at the end of the patch list; retain the user's existing profile config."""
import argparse
from datetime import datetime
import json
import hashlib
from pathlib import Path
import re
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--home', required=True)
parser.add_argument('--profiles', default='desktop,web')
args = parser.parse_args()
plugin = Path(__file__).resolve().parents[1] / 'app/dsh_plugin/index.mjs'
revision = hashlib.sha256(b''.join((plugin.parent / name).read_bytes()
    for name in ('index.mjs','companion-chat.mjs','persona.md','persona-maid.md','persona-brat.md'))).hexdigest()[:16]
plugin_uri = plugin.as_uri() + '?petBuild=' + revision
home = Path(args.home).resolve()
begin, end = '# whale-pet-bridge:begin', '# whale-pet-bridge:end'


def strip_bridge(text):
    """Drop only the bridge entry itself, so rows the host appended later survive."""
    lines = text.splitlines()
    kept, index = [], 0
    while index < len(lines):
        line = lines[index]
        if re.match(r'^-\s*insert:\s*$', line):
            stop = index + 1
            while stop < len(lines) and not re.match(r'^-', lines[stop]):
                stop += 1
            block = lines[index:stop]
            if any(row.strip() == '- id: whale-pet-bridge' for row in block):
                index = stop
                continue
            kept.extend(block)
            index = stop
            continue
        if line.strip() not in (begin, end):
            kept.append(line)
        index += 1
    kept = [line for line in kept if line.strip() != '[]']
    # A host rewrite can glue a marker onto the previous line; drop the text wherever it sits.
    joined = '\n'.join(kept).replace(begin, '').replace(end, '')
    return '\n'.join(row.rstrip() for row in joined.splitlines()).rstrip()


matched = 0
for profile in args.profiles.split(','):
    if profile not in ('desktop', 'web'):
        raise SystemExit('Unsupported profile')
    path = home / 'profiles' / profile / 'cordis.patch.yml'
    if not path.parent.is_dir():
        continue
    matched += 1
    original = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    value = strip_bridge(original)
    row = f'{begin}\n- insert:\n    - id: whale-pet-bridge\n      name: {json.dumps(plugin_uri, ensure_ascii=False)}\n      config:\n        profile: {profile}\n{end}\n'
    updated = (value + '\n\n' if value else '') + row
    if original == updated:
        print(profile + ': already installed')
        continue
    if path.exists():
        backup = path.with_name(path.name + '.whale-pet-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.bak')
        shutil.copy2(path, backup)
    path.write_text(updated, encoding='utf-8', newline='\n')
    print(profile + ': bridge row moved to the end of the patch list')

if not matched:
    raise SystemExit('No compatible dsh profile found. Start dsh Web or Desktop once and verify DSH_HOME.')
