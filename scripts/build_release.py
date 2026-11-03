"""Build an upgrade zip and manifest for a trusted public GitHub repository."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IGNORE = {'.env', '.git', '.github', '.krew_updates', 'data', 'logs', 'backups',
          'scripts', 'updates', '__pycache__', 'dist', '.pytest_cache'}
ROOT_FILES = {'VERSION','main.py','launcher.py','updater.py','upgrade.py','backup.py',
              'release_check.py','README.md','CHANGELOG.md','Dockerfile','compose.yaml',
              '.dockerignore','.gitignore','.env.example','release_notes.json'}


def build(repo: str, tag: str, out: Path) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Ожидается OWNER/REPO')
    version = (ROOT/'VERSION').read_text(encoding='utf8').strip()
    if tag != f'v{version}':
        raise ValueError(f'Git tag {tag!r} должен соответствовать VERSION v{version}')
    note = json.loads((ROOT/'release_notes.json').read_text(encoding='utf8'))
    if note.get('version') != version:
        raise ValueError('release_notes.json должен совпадать с VERSION')
    out.mkdir(parents=True,exist_ok=True)
    asset = out/'krew-update.zip'
    included = []
    for file in ROOT.rglob('*'):
        if not file.is_file():
            continue
        relative=file.relative_to(ROOT)
        if any(p in IGNORE for p in relative.parts) or file.suffix == '.pyc':
            continue
        if len(relative.parts)==1 and file.name not in ROOT_FILES:
            continue
        if len(relative.parts)>1 and relative.parts[0] not in ('krew','tests'):
            continue
        included.append((relative.as_posix(),file))
    included.sort()
    with zipfile.ZipFile(asset,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as zf:
        for name,path in included:
            info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100644<<16)
            zf.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
    # Verify that the updater can extract our own build.
    import sys
    sys.path.insert(0,str(ROOT))
    from updater import extract_verified_zip
    temp = out/'zip_check'
    names = extract_verified_zip(asset.read_bytes(),temp,version)
    assert names
    import shutil
    shutil.rmtree(temp)
    prerelease='-rc.' in version
    channel='beta' if prerelease else 'stable'
    manifest = {
        'schema':1,
        'channel':channel,
        'version':version,
        'url':f'https://github.com/{repo}/releases/download/{tag}/krew-update.zip',
        'sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),
    }
    (out/f'{channel}.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    readme='# '+note['title']+'\n\n'+'\n'.join('- '+x for x in note['changes'])+'\n'
    (out/'RELEASE_NOTES.md').write_text(readme,encoding='utf8')
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',required=True)
    parser.add_argument('--tag',required=True)
    parser.add_argument('--out',default=str(ROOT/'dist'))
    args=parser.parse_args()
    print(json.dumps(build(args.repository,args.tag,Path(args.out)),ensure_ascii=False,indent=2))
