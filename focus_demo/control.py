"""Settings policy, explicit agent actions, and task evidence lifecycle."""
import json
import time
import uuid
from pathlib import Path
from .common import write_json
from .sampling_settings import merge as sampling_settings
from .evidence_export import export_request,folder_for,user_export,user_verify,user_cleanup

_prompt_source=Path(__file__).resolve().parents[1]/'dsh-plugin/default-prompts.json'
DEFAULTS=json.loads((_prompt_source if _prompt_source.is_file() else Path(__file__).with_name('default_prompts.json')).read_text(encoding='utf-8'))
ACTIVE={'active','awaiting_extension','verified_waiting'}

class Control:
    def settings(self):
        stored=self.store.get('settings','global') or {}
        # Saved custom values win; a field missing from an older stored row falls
        # back to the shipped default instead of disappearing or raising.
        value={'id':'global',**DEFAULTS,**{key:stored[key] for key in DEFAULTS if key in stored},**sampling_settings(stored)}
        live=self.live() if value['protect_task_changes'] else []
        return {**value,'ui_locked':bool(live),'instructions_locked':bool(live),
                'heartbeat_locked':any(t['status'] in ACTIVE for t in live)}

    def configure(self,request,actor='ai',session_id=''):
        with self.lock:
            value=self.settings();patch=request.get('patch',{})
            if actor=='ui' and value['ui_locked']:raise ValueError('有任务或预约时，界面设置已锁定；请在监工聊天中商量修改。')
            if not isinstance(patch,dict) or not patch:raise ValueError('请提供需要修改的设置')
            allowed={'instructions','instructions_full','heartbeat_prompt','mascot_size','task_prompt','away_heartbeats','sampling','reporting','protect_task_changes'}
            if set(patch)-allowed:raise ValueError('未知设置字段')
            if value['instructions_locked'] and ({'instructions','instructions_full'} & set(patch)):raise ValueError('有任务或预约时，任何人都不能修改插件使用说明。')
            if 'heartbeat_prompt' in patch and value['heartbeat_locked']:raise ValueError('有进行中任务时不能修改全局心跳要求。')
            for key in ('instructions','instructions_full','heartbeat_prompt','task_prompt'):
                if key in patch and (not isinstance(patch[key],str) or not patch[key].strip()):raise ValueError(f'{key} 不能为空')
            if 'mascot_size' in patch and (type(patch['mascot_size']) is not int or not 80<=patch['mascot_size']<=320):raise ValueError('图片大小范围为80至320像素')
            if 'away_heartbeats' in patch and (type(patch['away_heartbeats']) is not int or not 2<=patch['away_heartbeats']<=10):raise ValueError('离席判定次数须为 2 至 10 的整数')
            if 'protect_task_changes' in patch:
                if type(patch['protect_task_changes']) is not bool:raise ValueError('防任务中修改模式必须是布尔值')
                if value['ui_locked'] and patch['protect_task_changes'] is not True:raise ValueError('有任务或预约时不能关闭防任务中修改模式')
            task=None
            if 'task_prompt' in patch:
                if actor!='ai':raise ValueError('任务附加提示词通过监工会话修改')
                task=self.task_for(request.get('task_id',''),session_id)
                if task['status'] not in {'scheduled',*ACTIVE}:raise ValueError('任务已结束')
            options=sampling_settings(value,{k:v for k,v in patch.items() if k in ('sampling','reporting')})
            if task:
                task['task_prompt']=patch['task_prompt'];self.store.save('task',task)
            global_patch={k:v for k,v in patch.items() if k!='task_prompt'}
            global_patch.update(options)
            if global_patch:
                self.store.save('settings',{'id':'global',**{k:value[k] for k in DEFAULTS},**global_patch})
            self.store.log('settings_changed',{'actor':actor,'fields':list(patch),'task_id':request.get('task_id')})
            self.sample=options["sampling"]["interval_seconds"]
            self.publish_settings();self.publish()
            return {'settings':self.settings(),'task':task}

    def finish_ui(self, request):
        with self.lock:
            if self.settings()['protect_task_changes']:
                raise ValueError('防任务中修改模式已开启，请在监工会话中结束任务')
            task=self.store.get('task',request['task_id'])
            if task is None:raise ValueError('任务不存在')
            return self.finish({'task_id':task['id'],'verdict':'cancelled','reason':'用户在插件界面手动结束任务'},task['session_id'])

    def publish_settings(self):
        path=self.directory/'settings.json';write_json(path,self.settings())
        if self.status_gid is not None:
            import os
            os.chown(path,0,self.status_gid);os.chmod(path,0o640)

    def act(self,request,session_id):
        with self.lock:
            task=self.task_for(request['task_id'],session_id)
            if task['status'] not in {'scheduled',*ACTIVE}:raise ValueError('任务已结束')
            action=request.get('action')
            if action in {'minimize_window','force_close'}:
                report=self.store.get('report',request.get('report_id',''))
                if not report or report['task_id']!=task['id'] or report['revision']!=task['revision']:raise ValueError('报告不属于当前任务版本')
                expected=report['effective']['evidence'].get(request.get('target_ref'))
                if not expected:raise ValueError('窗口证据不存在，请重新采集')  # 不再限制证据时效：动手时由执行器核对目标是否还在、还是不是它。
                payload={'expected':expected,'target_kind':request.get('target_kind','process')} if action=='force_close' else expected
                result=self.sensor.call('force_close' if action=='force_close' else 'minimize',payload) if self.sensor else {('closed' if action=='force_close' else 'minimized'):False,'reason':'无采集器'}
            elif action=='remind':
                message=request.get('message')
                if not isinstance(message,str) or not message.strip():raise ValueError('提醒内容不能为空')
                image=request.get('image','gentle')
                if image not in {'question','gentle','warning','urgent','start','celebrate','sleep','scheduled','watching','checking'}:raise ValueError('未知提醒形象')
                from urllib.parse import urlparse
                chat_url=request.get('chat_url','')
                if chat_url and (urlparse(chat_url).scheme!='http' or urlparse(chat_url).hostname!='127.0.0.1'):
                    raise ValueError('提醒只能跳转到本机 DSH')
                alert={'id':request.get('action_id') or str(uuid.uuid4()),'task_id':task['id'],'session_id':session_id,
                       'message':message,'image':image,'popup':True,'notification':True,'sound':True,
                       'chat_url':chat_url,'chat_registry':request.get('chat_registry'),'created_at':time.time()}
                old=self.store.get('alert',alert['id'])
                if old:return old
                try:
                    if not any(alert[k] for k in ('popup','notification','sound')):result={'popup':False,'notification':False,'sound':False,'errors':[]}
                    else:result=self.sensor.call('notify',alert) if self.sensor else {'error':'无桌面连接'}
                except Exception as e:result={'error':str(e)}
                alert['delivery']=result;self.store.save('alert',alert)
                result=alert
            else:raise ValueError('action 须为 remind、minimize_window 或 force_close')
            self.store.log('agent_action',{'task_id':task['id'],'action':action,'result':result})
            self.publish();return result

    def export_report(self,report,task):
        if not task.get('project_dir'):return {'error':'旧任务尚未关联项目目录；请通过 focus_revise 提供 project_dir。'}
        saved=self.store.get('export',report['id'])
        if saved:return saved
        payload,hashes=export_request(task,report,self.directory)
        if self.sensor:result=self.sensor.call('export',payload)
        else:result=user_export(payload)
        saved={'id':report['id'],'task_id':task['id'],'folder':payload['folder'],'sha256':hashes,'program_files':payload['program_files']}
        self.store.save('export',saved)
        return saved

    def verify_export(self,report,task):
        saved=self.export_report(report,task)
        if 'error' in saved:return saved
        request={'folder':saved['folder'],'names':list(saved['sha256'])}
        actual=self.sensor.call('verify_export',request) if self.sensor else user_verify(request)
        mismatches=[name for name,digest in saved['sha256'].items() if actual.get(name)!=digest]
        return {'folder':saved['folder'],'verified':not mismatches,'changed_or_missing':mismatches,
                'expected_sha256':saved['sha256']}

    def cleanup_task(self,task):
        task.pop('task_prompt',None)
        task.pop('cleanup_pending',None)
        if task.get('project_dir'):
            try:
                payload={'folder':str(folder_for(task))}
                if self.sensor:self.sensor.call('cleanup_export',payload)
                else:user_cleanup(payload)
            except Exception as e:
                self.store.log('evidence_cleanup_failed',{'task_id':task['id'],'error':str(e)})
                task['cleanup_pending']=True;self.store.save('task',task)
        self.store.save('task',task)
        with self.store.lock:
            self.store.db.execute('DELETE FROM samples WHERE task_id=?',(task['id'],))
            for kind in ('report','export','alert'):
                for item in self.store.all(kind):
                    if item.get('task_id')==task['id']:
                        self.store.db.execute('DELETE FROM documents WHERE kind=? AND id=?',(kind,item['id']))
            # Old revision audit rows must not retain the deleted per-task prompt.
            for row in self.store.db.execute('SELECT id,body FROM audit').fetchall():
                body=json.loads(row['body']);previous=body.get('previous')
                if isinstance(previous,dict) and previous.get('id')==task['id']:
                    previous.pop('task_prompt',None)
                    self.store.db.execute('UPDATE audit SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
            self.store.db.commit()
            self.store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.store.db.execute('VACUUM')
        if not any(t['status'] in ACTIVE for t in self.live()):
            for image in (self.directory/'screenshots').glob('*.png'):image.unlink(missing_ok=True)
            if self.sensor:
                try:self.sensor.call('cleanup_capture',{})
                except Exception as e:self.store.log('capture_cleanup_failed',{'error':str(e)})
