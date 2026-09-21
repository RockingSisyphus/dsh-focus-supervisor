"""Durable agreements and evidence. All semantic decisions belong to the DSH agent."""
from datetime import datetime
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
from .prompts import timeline, apply_time_patch
from .reports import EvidenceTools, overview

LIVE = {"scheduled", "active", "awaiting_extension", "verified_waiting"}


class Supervisor(TaskLifecycle, Control):
    def __init__(self, directory, lifecycle, sensor=None, interval=600, sample=2, test_mode=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.directory / "events.sqlite3")
        self.lifecycle, self.sensor = lifecycle, sensor
        self.interval, self.sample, self.test_mode = interval, sample, test_mode
        self.lock = threading.RLock()
        self.capture_error = None
        self.last_sample = None
        self.empty_since = time.time()
        self.shutting_down = False
        self.status_gid = None
        self.hold_reports = False
        self.presence = {"available": False}
        self.restored_tasks = {t["id"] for t in self.live()}

    def live(self):
        return [t for t in self.store.all("task") if t["status"] in LIVE]

    def ensure(self):
        # Explicit task admission, not polling, resets the existing idle timer.
        # Once exit has won this same lock, the caller must start a new service.
        with self.lock:
            if not self.shutting_down:
                if self.live():self.lifecycle.enable()
                else:self.empty_since=time.time()
            return self.state()

    def state(self):
        with self.lock:
            tasks = self.store.all("task")
            return {"server_time": time.time(), "tasks": tasks[-50:], "live": self.live(), "capture_error": self.capture_error,
                    "presence": self.presence, "notices": self.store.all("notice"), "needs_dsh": self.needs_dsh(),
                    "last_sample_at": self.last_sample, "effective_sampling":getattr(self,"effective_sampling",None), "test_mode": self.test_mode, "shutting_down": self.shutting_down,
                    "execution": getattr(self,"execution",{}), "interval": self.interval, "settings": self.settings(), "alerts": self.store.all("alert")[-20:], "events": self.store.logs(12),
                    "reports": [{k: r.get(k) for k in ("id", "task_id", "phase", "status", "created_at", "reason")}
                                for r in self.store.all("report")[-15:]]}

    def publish(self):
        write_json(self.directory / "status.json", self.state())
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
        if request.get("deadline_policy") not in {"stop", "discuss", "continue"}:
            raise ValueError("到时策略须为 stop、discuss 或 continue")
        return {"agreement": text.strip(), "start_at": start, "end_at": end,
                "allow_early_finish": request["allow_early_finish"], "deadline_policy": request["deadline_policy"]}

    def task_interval(self, task):
        return task.get("check_interval_seconds", self.interval)

    def configured_interval(self, request, default):
        value = request.get("check_interval_seconds", default)
        if type(value) is not int or value <= 0:
            raise ValueError("检查间隔必须为正整数秒")
        return value

    def check_conflicts(self, contract, exclude_id=None):
        now = time.time()
        conflicts = []
        for task in self.live():
            if task["id"] == exclude_id:
                continue
            overlap = contract["start_at"] < task["end_at"] and task["start_at"] < contract["end_at"]
            ongoing = (task["status"] in {"active", "awaiting_extension"}
                       and task["end_at"] <= now and task["deadline_policy"] != "stop"
                       and contract["start_at"] <= now < contract["end_at"])
            if overlap or ongoing:
                conflicts.append((task, ongoing))
        if conflicts:
            def describe(item):
                task, ongoing = item
                start = datetime.fromtimestamp(task["start_at"]).astimezone().isoformat()
                end = datetime.fromtimestamp(task["end_at"]).astimezone().isoformat()
                return (f'{task["id"]}：{task["agreement"]}；{start} 至 {end}；状态 {task["status"]}'
                        + ('（已超时但仍在监督）' if ongoing else ''))
            raise ValueError("任务时间冲突，未保存。冲突任务：\n" + "\n".join(map(describe, conflicts)))

    def plan(self, request, session_id):
        with self.lock:
            if self.shutting_down:
                raise ValueError("服务正在退出，请稍后重试创建任务")
            contract = self.agreement(request)
            contract["check_interval_seconds"] = self.configured_interval(request, self.interval)
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
            task = self.task_for(request["task_id"], session_id)
            if task["status"] not in LIVE:
                raise ValueError("任务已经结束")
            contract = self.agreement(request)
            contract["check_interval_seconds"] = self.configured_interval(request, self.task_interval(task))
            for key in ('task_prompt','project_dir'):
                if key in request:
                    value=request[key]
                    if not isinstance(value,str) or not value.strip():raise ValueError(f'{key} 不能为空')
                    if key=='project_dir':
                        if task.get('project_dir') and value!=task['project_dir']:raise ValueError('任务中不能移动证据目录')
                        if not Path(value).is_absolute() or not Path(value).is_dir():raise ValueError('项目目录不存在')
                        value=str(Path(value).resolve())
                    contract[key]=value
            self.check_conflicts(contract, exclude_id=task["id"])
            self.store.log("agreement_revised", {"previous": task, "reason": request["reason"]})
            task.update(contract, revision=task["revision"] + 1,
                        status="scheduled" if contract["start_at"] > time.time() else "active",
                        next_check=max(time.time(), contract["start_at"]) + contract["check_interval_seconds"], incident=None)
            self.cancel_reports(task["id"])
            self.store.save("task", task)
            self.publish()
            return task

    def cancel_reports(self, task_id, include_delivered=True):  # 功能：作废该任务的报告；待机时不动已交给 AI 的那份。
        for report in self.store.all("report"):
            if report["task_id"] == task_id and report["status"] in ({"preview", "pending", "delivered"} if include_delivered else {"preview", "pending"}):
                report["status"] = "cancelled"
                self.store.save("report", report)

    def finish(self, request, session_id):
        with self.lock:
            task = self.task_for(request["task_id"], session_id)
            if task["status"] not in LIVE:
                return task
            verdict = request["verdict"]
            if verdict not in {"completed", "cancelled", "not_completed"}:
                raise ValueError("未知的任务结束判断")
            # This is only an explicit timing agreement, never an essay/quiz gate.
            task["status"] = ("verified_waiting" if verdict == "completed" and
                              not task["allow_early_finish"] and time.time() < task["end_at"] else verdict)
            task["review"] = request["reason"]
            task["reviewed_at"] = time.time()
            if task["status"] != "verified_waiting":
                task["ended_at"] = time.time()
            self.store.save("task", task)
            self.cancel_reports(task["id"])
            if task["status"] not in LIVE:self.cleanup_task(task)
            self.store.log("agent_task_decision", {"task_id": task["id"], "verdict": verdict, "reason": request["reason"]})
            self.publish()
            return task

    def capture(self):
        with self.lock:
            active = [t for t in self.live() if t["status"] in {"active", "awaiting_extension"} and not t.get("standby")]
        if not active or not self.sensor:
            return
        try:
            options={k:self.settings()[k] for k in ("sampling","reporting")}
            self.sample=options["sampling"]["interval_seconds"]
            sample = self.sensor.call("capture", options)
            sample["settings"]=options
            self.effective_sampling={"at":sample["ts"],**options}
            with self.lock:
                for task in active:
                    current = self.store.get("task", task["id"])
                    if current["status"] not in {"active", "awaiting_extension"}:
                        continue
                    self.store.add_sample(task["id"], sample)
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
                    if task["status"] == "verified_waiting" or task["deadline_policy"] == "stop":
                        task.update(status="completed" if task["status"] == "verified_waiting" else "not_completed",
                                    ended_at=now, review="按事先约定在结束时间退出监督")
                        self.store.save("task", task)
                        self.cancel_reports(task["id"])
                        self.cleanup_task(task)
                        self.store.log("agreed_deadline", {"task_id": task["id"], "status": task["status"]})
                        continue
                    if task["status"] != "awaiting_extension":
                        task["status"] = "awaiting_extension"
                        self.store.save("task", task)
                        self.cancel_reports(task["id"])
                        self.make_report(task, "deadline", count_input=True)
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
        with self.lock:
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
                        "window_start":report["raw"].get("real_start"),"window_end":report["raw"].get("real_end"),"reporting":self.settings()["reporting"],"heartbeat_prompt":self.settings()['heartbeat_prompt'],"evidence_export":export}
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
            for task in self.live():
                task.update(status="recovered_not_completed", ended_at=time.time(), review=reason)
                self.store.save("task", task)
                self.cancel_reports(task["id"])
                self.cleanup_task(task)
            self.store.log("administrator_recovery", {"reason": reason})
            self.empty_since = time.time() - 10
            self.publish()
