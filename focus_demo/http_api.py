"""Shared HTTP request handling, independent of service installation and IPC."""
import json
import secrets
from http.server import BaseHTTPRequestHandler


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        token=getattr(self.server,'api_token',None)
        if token and not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
            self.respond(403,{'error':'Invalid backend token'});return
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 1_000_000:
                raise ValueError('请求过大或为空')
            request = json.loads(self.rfile.read(size))
            session = request.get('session_id', '')
            core = self.server.core
            if self.path == '/state':
                result = core.state()
            elif self.path == '/ensure':
                result=core.ensure()
            elif self.path == '/due':
                result = core.due()
            elif self.path == '/delivered':
                core.delivered(request['report_id'])
                result = {'ok': True}
            elif self.path == '/settings/ui':
                result=core.configure(request,'ui')
            elif self.path == '/settings/ai':
                result=core.configure(request,'ai',session)
            elif self.path == '/act':
                result=core.act(request,session)
            elif self.path == '/plan':
                if not session:
                    raise ValueError('需要 DSH 会话')
                result = core.plan(request, session)
            elif self.path == '/revise':
                result = core.revise(request, session)
            elif self.path == '/finish/ui':
                result = core.finish_ui(request)
            elif self.path == '/finish':
                result = core.finish(request, session)
            elif self.path == '/observe':
                result = core.observe(request, session)
            elif self.path == '/report':
                result = core.report_tool(request)
            elif self.path == '/check':
                task = core.task_for(request['task_id'], session)
                if task['status'] not in {'active', 'awaiting_extension'}:
                    raise ValueError('任务尚未开始或已经结束')
                core.capture()  # 真的采集一次；放在持锁区间之外，避免让心跳与待机判定排队等待。
                with core.lock:
                    for stale in [r for r in core.store.all('report') if r['task_id'] == task['id'] and r['status'] == 'pending']:
                        core.delivered(stale['id'])  # 新数据取代尚未处理的心跳报告，避免挡住下一次心跳。
                    result = core.make_report(core.store.get('task', task['id']), 'check', advance=False)
                    core.delivered(result['id'])  # 检查报告不当心跳再次投递。
                    result = core.report_tool({'report_id': result['id'], 'operation': 'get_overview'})
            elif self.path == '/test/preview':
                if not core.test_mode:
                    raise ValueError('只有测试模式可读取预览时间片')
                report = core.store.get('report', request['report_id'])
                if not report:
                    raise ValueError('报告不存在')
                result = {"report_id": report['id'], "status": report['status'],
                          "segments": [{k: s.get(k) for k in ('id', 'real_duration_seconds', 'duration_seconds', 'objects')}
                                       for s in report['effective']['segments']]}
            elif self.path == '/test/release':
                result = core.release_preview(request['report_id'])
            elif self.path == '/test/time':
                result = core.patch_time(request['report_id'], request['patch'])
            else:
                raise ValueError('未知接口；没有任意命令执行接口')
            self.respond(200, result)
        except Exception as error:
            self.respond(400, {'error': str(error)})

    def respond(self, code, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

