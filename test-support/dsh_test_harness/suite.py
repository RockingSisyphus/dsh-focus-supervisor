"""Build the same subprocess command on either platform from a suite group."""
def group_args(group,output):
    if group['kind']=='pytest':return ['-m','pytest',*group['tests'],'-q','--junitxml='+str(output/'junit.xml')]
    if group['kind']=='pack':
        args=[group['script'],'test','--output',str(output/'pack'),'--workers',str(group.get('workers',8)),*[arg for case in group['cases'] for arg in ('--case',case)]]
        if group.get('human_review'):args+=['--human-review','--human-step-delay',str(group.get('human_step_delay',1))]
        return args
    return [group['script'],'--output',str(output),*(['--human-review'] if group.get('human_review') else [])]


def resolve_groups(root,spec):
    """Optional JSON case discovery, shared by local and VM entry points."""
    import copy,json
    result=copy.deepcopy(spec)
    for group in result['groups']:
        discovery=group.pop('discover',None)
        if discovery:
            definitions=[json.loads(path.read_text(encoding='utf-8')) for path in sorted(root.glob(discovery['glob']))]
            group['cases']=[case['id'] for case in definitions if case.get('engine')==discovery['engine'] and case['id'] not in discovery.get('exclude',[])]
    return result
