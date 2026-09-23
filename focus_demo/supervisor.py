"""Durable agreements and evidence. All semantic decisions belong to the DSH agent."""
from datetime import datetime
import hashlib
import math
import os
import threading
import time
import uuid
from pathlib import Path

from .control import Control, ACTIVE
from .lifecycle import TaskLifecycle
from .common import write_json
from .store import Store
from .control_lock import ControlLock
from .prompts import timeline, apply_time_patch
from .reports import EvidenceTools, overview
from . import recurrence

LIVE = {"scheduled", "active", "awaiting_extension", "verified_waiting"}
# Exact v0.5.0 shipped defaults. Only these saved copies can move to new defaults;
# user-edited prompts remain untouched.
PREVIOUS_DEFAULT_PROMPT_HASHES = {
    'instructions': 'a8b5e7fd4562b7ba63eeb61ea072230b1bb4c1e54a1f4eb8c886c4f290d6a691',
    'instructions_full': '5398df1584f7e05d70334a24653f385c7b7d1133fd487f5a7dfa06cf0e3d3ac2',
    'heartbeat_prompt': 'e827eda1bc6931dab92f5fe5a602fd556adfdd4952130b538f3aec442a36a1fd',
}


class Supervisor(TaskLifecycle, Control):
    def __init__(self, directory, lifecycle, sensor=None, interval=600, sample=2, test_mode=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.directory / "events.sqlite3")
        self.lifecycle, self.sensor = lifecycle, sensor
        self.interval, self.sample, self.test_mode = interval, sample, test_mode
        self.lock = ControlLock()
        self.action_lock = threading.RLock()
        self.evidence_lock = threading.RLock()
        self.cleaning=set()
        self.capture_error = None
        self.last_sample = None
        self.empty_since = time.time()
        self.shutting_down = False
        self.status_gid = None
        self.hold_reports = False
        self.presence = {"available": False}
        self._migrate_task_defaults()
        inactive={s['id'] for s in self.store.all('series') if s['status']!='active'}
        for task in self.live():
            if task.get('series_id') in inactive:
                task.update(status='cancelled',ended_at=time.time(),review='所属循环已经结束',cleanup_pending=True)
                self.store.save('task',task)
                self.cancel_reports(task['id'])
        self.restored_tasks = {t["id"] for t in self.live()}
        for series in self.live_series():
            task=self.store.get('task',series['current_task_id']) if series.get('current_task_id') else None
            if task and task['status'] not in LIVE:
                if task.get('missed') and series['consumed']<=task['occurrence_index']:
                    series['missed']=series.get('missed',0)+1
                series['consumed']=max(series['consumed'],task['occurrence_index']+1)
                series['current_task_id']=None
                series['last_result']={'task_id':task['id'],'status':task['status'],'ended_at':task.get('ended_at')}
                self.store.save('series',series)
                task=None
            if not task:
                orphan=next((t for t in self.live() if t.get('series_id')==series['id']),None)
                if orphan:
                    series['current_task_id']=orphan['id']
                    series['next_start_at']=orphan['start_at']
                    series['next_end_at']=orphan['end_at']
                    self.store.save('series',series)
                else:
                    self._materialize_series(series)

    def live(self):
        return [t for t in self.store.all("task") if t["status"] in LIVE]

    def live_series(self):
        return [s for s in self.store.all('series') if s['status'] == 'active']

    def _migrate_task_defaults(self):
        stored = self.store.get('settings', 'global') or {}
        legacy = stored.get('protect_task_changes')
        for task in self.store.all('task'):
            changed = False
            if 'deadline_policy' in task:
                del task['deadline_policy']
                changed = True
            if task['status'] in LIVE and 'strictness' not in task:
                task['strictness'] = 'strict' if legacy else 'normal'
                changed = True
            if changed:self.store.save('task', task)
        for series in self.store.all('series'):
            if 'deadline_policy' in series['template']:
                del series['template']['deadline_policy']
                self.store.save('series', series)
        settings_changed = legacy is not None
        if legacy is not None:stored.pop('protect_task_changes')
        for key, digest in PREVIOUS_DEFAULT_PROMPT_HASHES.items():
            value = stored.get(key)
            if isinstance(value, str) and hashlib.sha256(value.encode()).hexdigest() == digest:
                stored.pop(key)
                settings_changed = True
        if settings_changed:self.store.save('settings', {'id': 'global', **stored})

    def capture_state(self):
        live=self.live()
        if any(t['status'] in {'active','awaiting_extension'} and not t.get('standby') for t in live):return 'collecting'
        if any(t.get('standby') for t in live):return 'away'
        if any(t['status']=='verified_waiting' for t in live):return 'verified_waiting'
        return 'scheduled' if live else 'idle'

    def ensure(self):
        # Explicit task admission, not polling, resets the existing idle timer.
        # Once exit has won this same lock, the caller must start a new service.
        with self.lock:
            if not self.shutting_down:
                if self.live():self.lifecycle.enable()
                else:self.empty_since=time.time()
            return self.state()

    def state(self):
        with self.store.read_lock:
            tasks = self.store.all("task")
            return {"server_time": time.time(), "tasks": tasks[-50:], "live": self.live(), "series": self.live_series(), "capture_error": self.capture_error,
                    "status_write_error":getattr(getattr(self,"publisher",None),"error",None), "capture_state":self.capture_state(), "presence": self.presence, "notices": self.store.all("notice"), "needs_dsh": self.needs_dsh(),
                    "last_sample_at": self.last_sample, "effective_sampling":getattr(self,"effective_sampling",None), "test_mode": self.test_mode, "shutting_down": self.shutting_down,
                    "execution": getattr(self,"execution",{}), "interval": self.interval, "settings": self.settings(), "alerts": self.store.all("alert")[-20:], "events": self.store.logs(12),
                    "reports": [{k: r.get(k) for k in ("id", "task_id", "phase", "status", "created_at", "reason")}
                                for r in self.store.all("report")[-15:]]}

    def publish(self):
        state=self.state()
        comparable={k:v for k,v in state.items() if k!='server_time'}
        if state['capture_state']!='collecting':
            # Idle counters remain live in /state; their clock advancing is not
            # a durable state change and must not cause writes while away.
            comparable['presence']={k:v for k,v in self.presence.items() if k in ('available','error')}
        publisher=getattr(self,'publisher',None)
        if comparable==getattr(self,'_published_state',None) and not getattr(publisher,'error',None):return
        import copy
        self._published_state=copy.deepcopy(comparable)
        if publisher:
            publisher.submit(self.directory/'status.json',state,self.status_gid)
            return
        write_json(self.directory / "status.json", state)
        if self.status_gid is not None:
            os.chown(self.directory / "status.json", 0, self.status_gid)
            os.chmod(self.directory / "status.json", 0o640)

    def task_for(self, task_id, session_id):
        task = self.store.get("task", task_id)
        if not task or task["session_id"] != session_id:
            raise ValueError("只能在协商此任务的 DSH 会话中管理它")
        return task

    @staticmethod
    def agreement(request):
        text = request.get("agreement")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("请提供已经和用户协商好的任务内容")
        start, end = float(request["start_at"]), float(request["end_at"])
        if not all(math.isfinite(v) for v in (start, end)) or end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        if type(request.get("allow_early_finish")) is not bool:
            raise ValueError("请明确是否允许提前结束")
        if 'deadline_policy' in request:
            raise ValueError('deadline_policy 参数已移除；任务到点自动结束')
        return {"agreement": text.strip(), "start_at": start, "end_at": end,
                "allow_early_finish": request["allow_early_finish"]}

    @staticmethod
    def strictness(request, default='normal'):
        value=request.get('strictness',default)
        if value not in {'normal','strict'}:raise ValueError('任务严苛度须为 normal 或 strict')
        return value

    def task_interval(self, task):
        return task.get("check_interval_seconds", self.interval)

    def configured_interval(self, request, default):
        value = request.get("check_interval_seconds", default)
        if type(value) is not int or value <= 0:
            raise ValueError("检查间隔必须为正整数秒")
        return value

    def check_conflicts(self, candidate, exclude_id=None, exclude_series=None, own_future=None):
        # A current_only revision changes this occurrence without changing its
        # series. Compare the actual live task and the untouched future rule.
        targets=[t for t in self.live() if t['id']!=exclude_id]
        for series in self.live_series():
            if series['id']==exclude_series:continue
            task=self.store.get('task',series['current_task_id']) if series.get('current_task_id') else None
            index=task['occurrence_index']+1 if task and task['status'] in LIVE else series['consumed']
            item=recurrence.occurrence(series,index)
            if item:targets.append({**series,'anchor_date':item['date'],'anchor_index':index})
        if own_future:targets.append(own_future)
        for target in targets:
            pair=recurrence.conflict(candidate,target)
            if pair:
                first=max(pair[0]['start_at'],pair[1]['start_at'])
                when=datetime.fromtimestamp(first).astimezone().isoformat()
                agreement=target.get('agreement') or target.get('template',{}).get('agreement','')
                raise ValueError(f"任务时间冲突，未保存。冲突任务：{target['id']}：{agreement}；首次重叠 {when}")

    def _materialize_series(self, series):
        if series['status']!='active' or series.get('current_task_id'):return None
        item, skipped=recurrence.next_occurrence(series,time.time(),series['consumed'])
        if skipped:
            series['consumed']+=skipped
            series['missed']=series.get('missed',0)+skipped
            self.store.log('series_missed',{'series_id':series['id'],'count':skipped})
        if item is None:
            series['status']='completed';series['ended_at']=time.time()
            series['template'].pop('task_prompt',None)
            self.store.save('series',series)
            return None
        task_id=series['first_task_id'] if item['index']==0 else f"task_{series['id'][7:]}_{item['index']}"
        task=self.store.get('task',task_id)
        if not task:
            contract={**series['template'],'start_at':item['start_at'],'end_at':item['end_at']}
            task={**contract,'id':task_id,'series_id':series['id'],'occurrence_index':item['index'],
                  'occurrence_date':item['date'],'session_id':series['session_id'],'revision':1,
                  'status':'scheduled' if item['start_at']>time.time() else 'active',
                  'created_at':time.time(),'next_check':max(time.time(),item['start_at'])+contract['check_interval_seconds'],
                  'cursor':0,'incident':None}
            self.store.save('task',task)
        series['current_task_id']=task_id
        series['next_start_at']=item['start_at']
        series['next_end_at']=item['end_at']
        self.store.save('series',series)
        self.lifecycle.enable()
        return task

    def _advance_series(self,task):
        series_id=task.get('series_id')
        if not series_id:return
        series=self.store.get('series',series_id)
        if not series or series.get('current_task_id')!=task['id']:return
        if task.get('missed') and series['consumed']<=task['occurrence_index']:
            series['missed']=series.get('missed',0)+1
        series['consumed']=max(series['consumed'],task['occurrence_index']+1)
        series['current_task_id']=None
        series['last_result']={'task_id':task['id'],'status':task['status'],'ended_at':task.get('ended_at')}
        self.store.save('series',series)
        self._materialize_series(series)

    def plan(self, request, session_id):
        with self.lock:
            if self.shutting_down:
                raise ValueError("服务正在退出，请稍后重试创建任务")
            contract = self.agreement(request)
            contract["check_interval_seconds"] = self.configured_interval(request, self.interval)
            contract['strictness']=self.strictness(request)
            # One durable ID supplied by the tool makes admission retries harmless.
            task_id = request["task_id"]
            old = self.store.get("task", task_id)
            if old:
                self.lifecycle.enable()
                return self.task_for(task_id, session_id)
            prompt=request.get("task_prompt")
            if not isinstance(prompt,str) or not prompt.strip():raise ValueError("创建任务必须填写 task_prompt")
            project=request.get("project_dir")
            if not isinstance(project,str) or not Path(project).is_absolute() or not Path(project).is_dir():raise ValueError("project_dir 必须为当前会话已存在的项目绝对目录")
            contract.update(task_prompt=prompt,project_dir=str(Path(project).resolve()))
            if request.get('repeat'):
                series_id='series_'+task_id.removeprefix('task_')
                series={**recurrence.schedule(contract,request['repeat'],recurrence.local_zone_name()),
                        'id':series_id,'session_id':session_id,'status':'active','consumed':0,'missed':0,
                        'current_task_id':None,'first_task_id':task_id,'template':{k:v for k,v in contract.items() if k not in ('start_at','end_at')}}
                self.check_conflicts(series)
                self.store.save('series',series)
                task=self._materialize_series(series)
                self.empty_since=None
                self.store.log('series_planned',{'series_id':series_id,'session_id':session_id})
                self.publish()
                return task or self.store.get('series',series_id)
            self.check_conflicts(contract)
            task = {**contract, "id": task_id, "session_id": session_id, "revision": 1,
                    "status": "scheduled" if contract["start_at"] > time.time() else "active",
                    "created_at": time.time(), "next_check": max(time.time(), contract["start_at"]) + contract["check_interval_seconds"],
                    "cursor": 0, "incident": None}
            self.lifecycle.enable()
            self.store.save("task", task)
            self.empty_since = None
            self.store.log("agreement_scheduled", {"task_id": task_id, "session_id": session_id})
            self.publish()
            return task

    def revise(self, request, session_id):
        with self.lock:
            series=self.store.get('series',request['series_id']) if request.get('series_id') else None
            if request.get('series_id') and not series:raise ValueError('循环不存在')
            if series and series['session_id']!=session_id:raise ValueError('只能在原监工会话中修改循环')
            if series and series['status']!='active':raise ValueError('循环已经结束')
            task = self.task_for(request.get('task_id') or (series or {})['current_task_id'], session_id)
            if series and task.get('series_id')!=series['id']:raise ValueError('任务不属于指定循环')
            if task.get('series_id'):
                if series and task['series_id']!=series['id']:raise ValueError('任务不属于指定循环')
                series=self.store.get('series',task['series_id'])
            if task["status"] not in LIVE:
                raise ValueError("任务已经结束")
            contract = self.agreement(request)
            contract["check_interval_seconds"] = self.configured_interval(request, self.task_interval(task))
            contract['strictness']=self.strictness(request,task.get('strictness','normal'))
            for key in ('task_prompt','project_dir'):
                if key in request:
                    value=request[key]
                    if not isinstance(value,str) or not value.strip():raise ValueError(f'{key} 不能为空')
                    if key=='project_dir':
                        if task.get('project_dir') and value!=task['project_dir']:raise ValueError('任务中不能移动证据目录')
                        if not Path(value).is_absolute() or not Path(value).is_dir():raise ValueError('项目目录不存在')
                        value=str(Path(value).resolve())
                    contract[key]=value
            scope=request.get('scope','current_and_future')
            if scope not in {'current_only','current_and_future'}:raise ValueError('修改范围须为 current_only 或 current_and_future')
            if series and scope=='current_and_future':
                candidate={**recurrence.schedule(contract,request.get('repeat') or series['repeat'],series['timezone'],task['occurrence_index']),
                           'id':series['id']}
                self.check_conflicts(candidate,exclude_id=task['id'],exclude_series=series['id'])
            else:
                if request.get('repeat'):raise ValueError('重复规则只能修改当前及未来轮次')
                future=None
                if series:
                    index=task['occurrence_index']+1
                    item=recurrence.occurrence(series,index)
                    if item:
                        future={**series,'anchor_date':item['date'],'anchor_index':index}
                self.check_conflicts(contract,exclude_id=task['id'],exclude_series=series['id'] if series else None,own_future=future)
            self.store.log("agreement_revised", {"previous": task, "reason": request["reason"]})
            task.update(contract, revision=task["revision"] + 1,
                        status="scheduled" if contract["start_at"] > time.time() else "active",
                        next_check=max(time.time(), contract["start_at"]) + contract["check_interval_seconds"], incident=None)
            self.cancel_reports(task["id"])
            self.store.save("task", task)
            if series and scope=='current_and_future':
                series.update(candidate)
                series['template']={k:v for k,v in task.items() if k in ('agreement','allow_early_finish','check_interval_seconds','strictness','task_prompt','project_dir')}
                series['next_start_at']=task['start_at'];series['next_end_at']=task['end_at']
                self.store.save('series',series)
            self.publish()
            return task

    def cancel_reports(self, task_id, include_delivered=True):  # 功能：作废该任务的报告；待机时不动已交给 AI 的那份。
        for report in self.store.all("report"):
            if report["task_id"] == task_id and report["status"] in ({"preview", "pending", "delivered"} if include_delivered else {"preview", "pending"}):
                report["status"] = "cancelled"
                self.store.save("report", report)

    def finish(self, request, session_id):
        with self.lock:
            series=self.store.get('series',request['series_id']) if request.get('series_id') else None
            if request.get('series_id') and not series:raise ValueError('循环不存在')
            if series and series['session_id']!=session_id:raise ValueError('只能在原监工会话中结束循环')
            task = self.task_for(request.get('task_id') or (series or {})['current_task_id'], session_id)
            if series and task.get('series_id')!=series['id']:raise ValueError('任务不属于指定循环')
            if task.get('series_id'):
                if series and task['series_id']!=series['id']:raise ValueError('任务不属于指定循环')
                series=self.store.get('series',task['series_id'])
                if request.get('scope') not in {'current_only','entire_series'}:
                    raise ValueError('循环结束须选择 current_only 或 entire_series')
            if task["status"] not in LIVE:
                return task
            verdict = request["verdict"]
            if verdict not in {"completed", "cancelled", "not_completed"}:
                raise ValueError("未知的任务结束判断")
            # This is only an explicit timing agreement, never an essay/quiz gate.
            task["status"] = ("verified_waiting" if request.get('scope')!='entire_series' and verdict == "completed" and
                              not task["allow_early_finish"] and time.time() < task["end_at"] else verdict)
            task["review"] = request["reason"]
            task["reviewed_at"] = time.time()
            if task["status"] != "verified_waiting":
                task["ended_at"] = time.time()
            if series and request.get('scope')=='entire_series':
                series['status']='cancelled';series['ended_at']=time.time()
                series['template'].pop('task_prompt',None)
                self.store.save('series',series)
            self.store.save("task", task)
            self.cancel_reports(task["id"])
            if task["status"] not in LIVE:
                self.cleanup_task(task)
                self._advance_series(task)
            self.store.log("agent_task_decision", {"task_id": task["id"], "verdict": verdict, "reason": request["reason"]})
            self.publish()
            return task

    def capture(self):
        with self.lock:
            active = [t for t in self.live() if t["status"] in {"active", "awaiting_extension"} and not t.get("standby")]
        if not self.sensor:return
        if not active:
            if getattr(self,'collecting',False):
                self.sensor.call('cleanup_capture',{})
                self.collecting=False
            return
        self.collecting=True
        try:
            options={k:self.settings()[k] for k in ("sampling","reporting")}
            self.sample=options["sampling"]["interval_seconds"]
            sample = self.sensor.call("capture", options)
            sample["settings"]=options
            self.effective_sampling={"at":sample["ts"],**options}
            accepted=False
            for task in active:
                accepted=self.store.add_live_sample(task['id'],sample) is not None or accepted
            with self.lock:
                if accepted:
                    self.last_sample = sample["ts"]
                    self.capture_error = None if sample["desktop"].get("available") else "; ".join(sample["desktop"].get("limitations", []))
        except Exception as error:
            self.capture_error = str(error)

    def make_report(self, task, phase="monitor", count_input=False, advance=True):
        if not self.presence.get("available"):self.poll_presence()
        if count_input and self.track_input(task):
            # The plugin confirmed the absence itself: this heartbeat is not sent.
            # 已经交给 AI 的报告不作废：否则 AI 紧接着的 focus_observe 会被告知"报告已结束"。
            self.cancel_reports(task["id"], include_delivered=False)
            task["next_check"] = time.time() + self.task_interval(task)
            self.store.save("task", task)
            self.publish()
            return None
        samples = self.store.samples(task["id"], task["cursor"])
        raw = timeline(samples, self.sample)
        from .activity import activity_changes
        earlier = [r for r in self.store.all('report') if r['task_id']==task['id']]
        previous = max(earlier,key=lambda r:r['created_at']) if earlier else None
        raw['activity_changes'] = activity_changes(samples,raw['evidence'],
            previous['raw'].get('activity_changes',[]) if previous else [])
        report = {"id": "report_" + uuid.uuid4().hex, "task_id": task["id"],
                  "session_id": task["session_id"], "revision": task["revision"],
                  "phase": phase, "presence":dict(self.presence), "input_activity":self.input_activity(task),
                  "created_at": time.time(), "status": "preview" if self.test_mode and self.hold_reports else "pending",
                  "request_id": str(uuid.uuid4()), "raw": raw, "settings":{k:self.settings()[k] for k in ("sampling","reporting")},
                  "effective": apply_time_patch(raw, {}, True), "test_mode": self.test_mode}
        self.store.save("report", report)
        if advance:  # 按需取证的检查报告只读新数据，不改心跳节奏与游标。
            task["cursor"] = samples[-1]["sample_id"] if samples else task["cursor"]
            task["next_check"] = time.time() + self.task_interval(task)
            self.store.save("task", task)
        return report

    def tick(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            for task in self.live():
                if self.restore_timing(task, now):continue
                if now >= task["end_at"]:
                    task.update(status="completed" if task["status"] == "verified_waiting" else "not_completed",
                                ended_at=now, review="按事先约定在结束时间退出监督",standby=False)
                    self.store.save("task", task)
                    self.cancel_reports(task["id"])
                    self.cleanup_task(task)
                    self._advance_series(task)
                    self.store.log("agreed_deadline", {"task_id": task["id"], "status": task["status"]})
                    continue
                if task["status"] not in {"active", "awaiting_extension"}:
                    continue
                if not task.get('start_report_sent'):
                    task['start_report_sent']=True
                    self.store.save('task',task)
                    self.make_report(task,'start',count_input=True)
                outstanding = any(r["task_id"] == task["id"] and r["status"] in {"preview", "pending"}
                                  for r in self.store.all("report"))
                if not outstanding and now >= task["next_check"]:
                    self.make_report(task, "followup" if task.get("incident") else "monitor", count_input=True)
            for ended in self.store.all('task'):
                if ended.get('cleanup_pending'):self.cleanup_task(ended)
            if self.live():
                self.empty_since = None
            elif self.empty_since is None:
                self.empty_since = now
            self.publish()

    def due(self):
        with self.lock:
            # An accepted DSH prompt is durably delivered once; its agent closes
            # the report via focus_observe. No repeated wake-up loop while busy.
            return [{k: r[k] for k in ("id", "task_id", "session_id", "phase", "request_id")}
                    for r in self.store.all("report") if r["status"] == "pending"]

    def delivered(self, report_id):
        with self.lock:
            report = self.store.get("report", report_id)
            if report and report["status"] == "pending":
                report["status"] = "delivered"
                report["delivered_at"] = time.time()
                self.store.save("report", report)

    def report_tool(self, request):
        with self.evidence_lock:
            report = self.store.get("report", request["report_id"])
            if not report:raise ValueError("报告不存在或已随任务结束清理")
            task = self.store.get('task',report['task_id'])
            if request['operation']=='verify_files':return self.verify_export(report,task)
            if request['operation']=='get_overview':
                try:export=self.export_report(report,task)
                except Exception as error:export={'error':str(error)}
                result={"task":task,"overview":overview(report['effective']),"report_id":report['id'],
                        "presence":report.get("presence",{}),"input_activity":report.get("input_activity",{}),"phase":report['phase'],"capture_error":self.capture_error,"test_mode":self.test_mode,
                        "test_time_override":report['effective'].get('test_time_override',False),
                        "real_observed_seconds":sum(s['real_duration_seconds'] for s in report['raw']['segments']),
                        "window_start":report["raw"].get("real_start"),"window_end":report["raw"].get("real_end"),"reporting":self.settings()["reporting"],"heartbeat_prompt":self.settings()['heartbeat_prompt'],
                        "strict_heartbeat_prompt":self.settings()['strict_heartbeat_prompt'] if task.get('strictness')=='strict' else None,"evidence_export":export}
                for row in result['overview']['programs']:row['detail_file']=export.get('program_files',{}).get(row['id'])
                images=EvidenceTools(report['effective'],self.directory)
                try:result.update(images.initial_desktop())
                except Exception:pass
                return result
            return EvidenceTools(report['effective'],self.directory,reporting=self.settings()['reporting']).call(request['operation'],request.get('arguments',{}))

    def observe(self, request, session_id):
        with self.lock:
            report = self.store.get("report", request["report_id"])
            if not report:
                raise ValueError("报告不存在")
            task = self.task_for(report["task_id"], session_id)
            if task["status"] not in LIVE or task["revision"] != report["revision"] or report["status"] not in {"pending", "delivered"}:
                raise ValueError("报告已结束或任务已经改变")
            decision = request["decision"]
            if decision not in {"on_task", "uncertain", "suspect", "returned", "off_task"}:
                raise ValueError("未知的观察判断")
            if request.get('close_window'):raise ValueError('最小化或强杀请调用统一 focus_act API')
            outcome = None
            if decision == "suspect":
                if not task.get("incident"):
                    incident = {"id": "incident_" + uuid.uuid4().hex, "task_id": task["id"],
                                "opened_at": time.time(), "question": request.get("reason"),
                                "reference": request.get("target_ref"), "state": "awaiting_explanation"}
                    task["incident"] = incident["id"]
                    self.store.save("incident", incident)
            elif decision in {"returned", "on_task"} and task.get("incident"):
                incident = self.store.get("incident", task["incident"])
                incident.update(state="resolved", reason=request["reason"], ended_at=time.time())
                self.store.save("incident", incident)
                task["incident"] = None
                outcome = {"incident_id": incident["id"], "state": incident["state"]}
            if task.get("incident") and decision == "suspect":
                incident = self.store.get("incident", task["incident"])
                target = report["effective"]["evidence"].get(request.get("target_ref"), {})
                outcome = {"incident_id": incident["id"], "state": incident["state"]}
                incident.setdefault("target_id", target.get("id"))
                self.store.save("incident", incident)
            self.observe_presence(task,report,request)
            report.update(status="reviewed", decision=decision, reason=request["reason"], action=outcome)
            self.store.save("report", report)
            self.store.save("task", task)
            self.store.log("agent_observation", {"task_id": task["id"], "report_id": report["id"], "decision": decision,
                                                "reason": request["reason"], "action": outcome})
            self.publish()
            return {"task": task, "action": outcome}

    def patch_time(self, report_id, patch):
        with self.lock:
            if not self.test_mode:
                raise ValueError("只有测试模式允许修改时间")
            report = self.store.get("report", report_id)
            if not report or report["status"] not in {"preview", "pending"}:
                raise ValueError("只能修改尚未发送的报告")
            report["effective"] = apply_time_patch(report["raw"], patch, True)
            self.store.save("report", report)
            return {"report_id": report_id, "patch": patch}

    def release_preview(self, report_id):
        with self.lock:
            report = self.store.get("report", report_id)
            if not self.test_mode or not report or report["status"] != "preview":
                raise ValueError("只能发送测试模式的预览报告")
            report["status"] = "pending"
            self.store.save("report", report)
            return {"report_id": report_id, "status": "pending"}

    def recover(self, reason):
        with self.lock:
            for series in self.live_series():
                series.update(status='cancelled',ended_at=time.time())
                series['template'].pop('task_prompt',None)
                self.store.save('series',series)
            for task in self.live():
                task.update(status="recovered_not_completed", ended_at=time.time(), review=reason)
                self.store.save("task", task)
                self.cancel_reports(task["id"])
                self.cleanup_task(task)
            self.store.log("administrator_recovery", {"reason": reason})
            self.empty_since = time.time() - 10
            self.publish()
