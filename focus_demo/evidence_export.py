"""Portable evidence files; trusted hashes remain in the supervisor database."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from .reports import overview, build_reports


def folder_for(task):
    return Path(task['project_dir'])/'.dafeiyu'/('task-'+hashlib.sha256(task['id'].encode()).hexdigest()[:20])


def export_request(task, report, directory):
    files={}
    def document(name,value):
        files[name]=base64.b64encode(json.dumps(value,ensure_ascii=False,indent=2).encode()).decode()
    effective=report['effective']
    summary=overview(effective)
    document('browser-snapshots.json', {'note': summary['browser_semantics']['note'], 'snapshots': effective.get('browser_snapshots', [])})
    document('timeline.json',effective)
    document('raw-timeline.json',report['raw'])
    programs=build_reports(effective)
    program_files={}
    for number,(key,program) in enumerate(programs.items()):
        filename=f'program-{number+1}.json';program_files[key]=filename
        document(filename,{**program,'evidence':{ref:effective['evidence'][ref] for ref in program['evidence_refs'] if ref in effective['evidence']}})
    for row in summary['programs']:row['detail_file']=program_files.get(row['id'])
    summary['program_files']=program_files
    document('overview.json',summary)
    # Collect images referenced by the frozen evidence, without arbitrary paths.
    def images(value):
        if isinstance(value,dict):
            path=value.get('path')
            if isinstance(path,str):path=path.replace('\\','/')
            if isinstance(path,str) and path.startswith('screenshots/') and Path(path).name.endswith('.png'):
                source=Path(directory)/'screenshots'/Path(path).name
                if source.is_file():files['screenshots/'+source.name]=base64.b64encode(source.read_bytes()).decode()
            for item in value.values():images(item)
        elif isinstance(value,list):
            for item in value:images(item)
    images(effective)
    hashes={name:hashlib.sha256(base64.b64decode(data)).hexdigest() for name,data in files.items()}
    document('manifest.json',{'report_id':report['id'],'sha256':hashes,'note':'可信校验值保存在后台；调用 focus_report verify_files 核验。'})
    return {'folder':str(folder_for(task)/report['id']),'files':files,'program_files':program_files},hashes


def user_export(request):
    """Runs as the desktop user, never root, so project paths cannot elevate writes."""
    folder=Path(request['folder'])
    if folder.is_symlink():raise ValueError('证据目录被替换为链接')
    folder.mkdir(parents=True,exist_ok=True)
    for name,data in request['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('无效证据路径')
        target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.parent.resolve().is_relative_to(folder.resolve()):raise ValueError('证据子目录被替换')
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.writing-',delete=False) as f:
            temporary=Path(f.name)
            try:f.write(base64.b64decode(data))
            except Exception:
                temporary.unlink(missing_ok=True);raise
        try:os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)
    return {'folder':str(folder),'written':len(request['files'])}


def user_verify(request):
    folder=Path(request['folder']);result={}
    for name in request['names']:
        target=folder/name
        try:
            if not target.resolve().is_relative_to(folder.resolve()):raise ValueError('outside')
            result[name]=hashlib.sha256(target.read_bytes()).hexdigest()
        except (OSError,ValueError):result[name]=None
    return result


def user_cleanup(request):
    folder=Path(request['folder'])
    if not folder.name.startswith('task-') or folder.parent.name!='.dafeiyu':raise ValueError('不是任务证据目录')
    if folder.is_symlink():folder.unlink()
    elif folder.exists():shutil.rmtree(folder)
    return {'removed':True}
