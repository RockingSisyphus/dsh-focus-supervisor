#!/usr/bin/env python3
"""Install the packaged DSH plugin, preserving the existing profile and packages."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--modules", type=Path, required=True, help="正在运行的 DSH 的 node_modules 目录")
parser.add_argument("--profile", type=Path, default=Path.home() / ".dsh/profiles/web")
parser.add_argument('--no-autostart',action='store_true',help='Skip DSH restart entry when deliberately installing an ephemeral profile')
parser.add_argument('--config-json',default='{}',help='Backend configuration for this installation')
args = parser.parse_args()
modules = args.modules.resolve()
profile = args.profile.resolve()
profile.mkdir(parents=True,exist_ok=True)
manifest = profile/'package.json'
if not manifest.exists():
    manifest.write_text(json.dumps({'private':True,'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],'patchReload':'live'}}}),encoding='utf-8')
patch = profile/'cordis.patch.yml'
if not patch.exists():patch.write_text('[]\n',encoding='utf-8')
# Package registration is the same public CLI used by the UI installation route.
# No repository node_modules link or file:// production overlay is required.
# DSH/pnpm retains file: dependencies: the package must outlive this command.
packages = profile/'.plugin-packages'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
packages.mkdir(parents=True)
result = subprocess.run([shutil.which('npm') or 'npm', 'pack', '--pack-destination', str(packages)], cwd=root/'dsh-plugin', capture_output=True, text=True, encoding='utf-8', check=True)
name = next(line.strip() for line in reversed(result.stdout.splitlines()) if line.strip().endswith('.tgz'))
package = packages/name
metadata = json.loads(manifest.read_text(encoding='utf-8'))
if 'dsh-focus-supervisor' in metadata.get('dependencies', {}):
    shutil.copy2(manifest, packages/'package.before.json')
    metadata['dependencies']['dsh-focus-supervisor'] = 'file:'+str(package)
    manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
env = {**os.environ, 'DSH_HOME': str(profile.parent.parent)}
subprocess.run(['node', str(modules/'@deepseek-ai/dsh/lib/bin.js'), 'plugin', '--profile', profile.name, 'add', str(package)], cwd=profile, env=env, check=True)
content = patch.read_text(encoding='utf-8')
# Use DSH's existing YAML dependency; installation needs no extra Python package.
updated = subprocess.run(['node', str(root/'scripts/profile-migration.mjs'), str(modules/'@deepseek-ai/dsh/package.json'), args.config_json], input=content, capture_output=True, text=True, encoding='utf-8', check=True).stdout
if updated != content:
    shutil.copy2(patch, patch.with_name(patch.name+'.before-package-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
content = updated
patch.write_text(content,encoding='utf-8')
print(f'已通过 dsh plugin add 安装正式包：{profile}。未重启 DSH。')

if not args.no_autostart:
    subprocess.run([sys.executable,str(root/'scripts/dsh-autostart.py'),'--modules',str(modules),'--home',str(args.profile.resolve().parent.parent)],check=True)
