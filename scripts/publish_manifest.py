"""Publish the versioned manifest into GitHub's default branch via GitHub API.

Intended for GitHub Actions only; uses GITHUB_TOKEN with contents:write.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from updater import parse_version

API='https://api.github.com'

def request(url, token, method='GET', data=None):
    req=Request(url,data=None if data is None else json.dumps(data).encode('utf8'),method=method,
                headers={'Authorization': 'Bearer '+token,'Accept':'application/vnd.github+json',
                         'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=25) as response:
            return json.loads(response.read().decode('utf8'))
    except HTTPError as exc:
        if exc.code == 404 and method=='GET':
            return None
        raise RuntimeError(f'GitHub API HTTP {exc.code}') from None


def publish(repo: str, channel: str, manifest: Path, token: str):
    if not token:
        raise ValueError('Missing GITHUB_TOKEN')
    if channel not in ('beta','stable'):
        raise ValueError('Invalid channel')
    base=f'{API}/repos/{repo}'
    details=request(base,token)
    if not details or not details.get('default_branch'):
        raise ValueError('Repository default branch unknown')
    branch=details['default_branch']
    path=f'updates/{channel}.json'
    url=base+'/contents/'+path
    existing=request(url+'?ref='+branch,token)
    new_data=json.loads(manifest.read_text(encoding='utf8'))
    if new_data.get('channel')!=channel:
        raise ValueError('Wrong manifest channel')
    # Never roll back the public update pointer to an older version.
    if existing:
        old_data=json.loads(base64.b64decode(existing['content']).decode('utf8'))
        if parse_version(old_data['version'])>parse_version(new_data['version']):
            raise ValueError('Refusing to publish an older manifest')
        if old_data['version']==new_data['version']:
            if old_data==new_data:
                return 'Already published'
            raise ValueError('Existing version has different checksum; tags must be immutable')
    body={'message':f'chore: publish KREW {new_data["version"]} ({channel}) [skip ci]',
          'content':base64.b64encode(manifest.read_bytes()).decode('ascii'),
          'branch':branch}
    if existing:
        body['sha']=existing['sha']
    request(url,token,method='PUT',data=body)
    return f'Updated {path} on {branch}'

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',required=True)
    parser.add_argument('--channel',required=True,choices=('beta','stable'))
    parser.add_argument('--file',required=True)
    args=parser.parse_args()
    print(publish(args.repository,args.channel,Path(args.file),os.getenv('GITHUB_TOKEN','')))
