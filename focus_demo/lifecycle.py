"""Task timing, idle observation and small durable notifications to DSH."""
import time
import uuid


class TaskLifecycle:
    def notice(self, task, kind, message, **extra):
        item={'id':'notice_'+uuid.uuid4().hex,'session_id':task['session_id'],'task_id':task['id'],
              'kind':kind,'message':message,'agreement':task['agreement'],'created_at':time.time(),**extra}
        self.store.save('notice',item)
        return item

    def invalidate(self, task, kind, message, now):
        task.update(status='invalidated',ended_at=now,review=message,standby=False)
        self.store.save('task',task)
        self.cancel_reports(task['id'])
        self.cleanup_task(task)
        self.notice(task,kind,message)
        self.store.log('task_invalidated',{'task_id':task['id'],'reason':kind})

    def needs_dsh(self):
        return (any(t['status'] in {'active','awaiting_extension'} and not t.get('standby') for t in self.live())
                or any(not n.get('wake_requested_at') for n in self.store.all('notice')))

    def notices_woken(self):
        for item in self.store.all('notice'):
            if not item.get('wake_requested_at'):
                item['wake_requested_at']=time.time();self.store.save('notice',item)

    def poll_presence(self):
        if not self.sensor or not any(t['status'] in {'active','awaiting_extension'} for t in self.live()):return
        try:value=self.sensor.call('presence')
        except Exception as error:value={'available':False,'error':str(error)}
        with self.lock:
            self.presence=value
            if not value.get('available'):return
            now=time.time()
            for task in self.live():
                if not task.get('standby'):continue
                if value['last_input_at'] <= task.get('absence_input_at',value['last_input_at'])+0.5:continue
                if now>=task['end_at']:
                    self.invalidate(task,'away_until_end','用户中途离席，直到任务结束后才回来；任务已作废，采集资料已清理。',now)
                else:
                    task.update(standby=False,away_confirmations=0,no_input_reports=0,no_input_in_report=False,
                                absence_input_at=value['last_input_at'],next_check=now)
                    self.store.save('task',task)
                    self.cancel_reports(task['id'])
                    self.make_report(task,'returned_to_computer')
                    self.notice(task,'returned','检测到新的鼠标或键盘活动，用户已回来，恢复监督。')
            self.publish()

    def away_heartbeats(self):
        value=self.settings().get('away_heartbeats')
        return value if type(value) is int and 2<=value<=10 else 3

    def input_activity(self, task):
        """Report what the collector observed; unavailable evidence is never called absence."""
        value=self.presence or {}
        limit=self.away_heartbeats()
        count=task.get('no_input_reports',0)
        idle=value.get('idle_seconds')
        available=bool(value.get('available')) and value.get('last_input_at') is not None
        return {'available':available,'idle_seconds':round(idle,1) if isinstance(idle,(int,float)) else None,
                'no_input_in_report':task.get('no_input_in_report') if available else None,
                'consecutive_no_input_heartbeats':count,'heartbeats_until_standby':max(0,limit-count),'away_heartbeats':limit}

    def track_input(self, task):
        """One real input check per scheduled heartbeat; the plugin, not the model, owns standby."""
        value=self.presence or {}
        if not value.get('available') or value.get('last_input_at') is None:
            task['no_input_in_report']=None
            return False
        last=value['last_input_at']
        previous=task.get('absence_input_at')
        had_input=previous is None or last>previous+0.5
        task['absence_input_at']=last
        if had_input:
            task.update(no_input_reports=0,no_input_in_report=False)
            return False
        task['no_input_reports']=task.get('no_input_reports',0)+1
        task['no_input_in_report']=True
        limit=self.away_heartbeats()
        if task['no_input_reports']>=limit:
            task.update(standby=True,standby_since=time.time())
            self.store.log('standby_entered',{'task_id':task['id'],'reason':'no_input_heartbeats',
                'heartbeats':task['no_input_reports'],'limit':limit,'idle_seconds':value.get('idle_seconds')})
            return True
        return False

    def observe_presence(self, task, report, request):
        presence=request.get('presence','unknown')
        if presence not in {'away','present','unknown'}:raise ValueError('presence 须为 away、present 或 unknown')
        # The model's reading is evidence only: standby is decided by real input activity.
        task['agent_presence']=presence
        task['agent_presence_at']=time.time()

    def restore_timing(self, task, now):
        """Return True when this task needs no further tick processing."""
        restored=task['id'] in self.restored_tasks
        self.restored_tasks.discard(task['id'])
        if task.get('standby'):return True  # Keep input detection even beyond end_at, per agreement.
        if task['status']=='scheduled':
            if now>=task['end_at']:
                self.invalidate(task,'missed','预约期间一直未开工，整个任务时段已经过去；任务已作废，资料已清理。',now)
                return True
            if now>=task['start_at']:
                task.update(status='active',late_seconds=max(0,now-task['start_at']))
                if restored:self.notice(task,'late_start',f"用户开机迟到了 {task['late_seconds']:.0f} 秒；现在开始剩余时段的监督。",late_seconds=task['late_seconds'])
                self.store.save('task',task)
        elif restored and task['status'] in {'active','awaiting_extension'}:
            if now>=task['end_at']:
                self.invalidate(task,'offline_until_end','任务进行中关机，重新开机时任务已结束；任务已作废，资料已清理。',now)
                return True
            self.cancel_reports(task['id'])
            self.make_report(task,'resumed_after_restart',count_input=True)
        return False
