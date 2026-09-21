#!/usr/bin/env python3
"""Export the current source without local history or private audit evidence."""
import argparse
from pathlib import Path
import shutil
import subprocess

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('destination',type=Path)
a=p.parse_args()
a.destination.mkdir(parents=True,exist_ok=True)
# The local checkout keeps historical audits; the public tree contains current docs.
public_docs={'architecture.md','usage.md','known-issues.md','sampling-settings.md'}
names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
for name in dict.fromkeys(names):
    if not name:continue
    source=root/name
    if not source.is_file():continue
    if name.startswith('docs/') and name.removeprefix('docs/') not in public_docs:continue
    if name=='DSH_TRIAL.md':continue
    target=a.destination/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
for source in (root/'docs/public').glob('*.md'):
    shutil.copy2(source,a.destination/'docs'/source.name)
print(a.destination)
