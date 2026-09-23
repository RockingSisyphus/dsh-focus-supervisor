"""Civil-time recurrence and one conflict checker for single and repeating tasks."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def local_zone_name():
    from tzlocal import get_localzone_name
    return get_localzone_name()


def normalize_repeat(value):
    if not isinstance(value, dict) or value.get('frequency') not in {'daily', 'weekly'}:
        raise ValueError('重复规则 frequency 须为 daily 或 weekly')
    days = value.get('weekdays', [])
    if value['frequency'] == 'weekly':
        if not isinstance(days, list) or not days or any(type(day) is not int or day not in range(1, 8) for day in days):
            raise ValueError('每周重复须给出 ISO 星期数 1 至 7')
        days = sorted(set(days))
    else:
        days = []
    until = value.get('until')
    if until is not None:
        try: until = date.fromisoformat(until).isoformat()
        except (TypeError, ValueError): raise ValueError('重复截止日期须为 YYYY-MM-DD') from None
    count = value.get('count')
    if count is not None and (type(count) is not int or count <= 0):
        raise ValueError('重复次数须为正整数')
    if until is not None and count is not None:
        raise ValueError('截止日期与总次数只能选择一种')
    return {'frequency': value['frequency'], 'weekdays': days, 'until': until, 'count': count}


def _resolve(day, clock, zone):
    """Choose the first fold; move a nonexistent wall time to its first valid minute."""
    naive = datetime.combine(day, time.fromisoformat(clock))
    for minutes in range(181):
        candidate = (naive + timedelta(minutes=minutes)).replace(tzinfo=zone, fold=0)
        roundtrip = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == naive + timedelta(minutes=minutes):
            return candidate.timestamp()
    raise ValueError('无法解析本地预约时间')


def schedule(contract, repeat, zone_name, anchor_index=0):
    zone = ZoneInfo(zone_name)
    start = datetime.fromtimestamp(contract['start_at'], zone)
    end = datetime.fromtimestamp(contract['end_at'], zone)
    result = {'repeat': normalize_repeat(repeat), 'timezone': zone_name,
              'anchor_date': start.date().isoformat(), 'anchor_index': anchor_index,
              'start_clock': start.timetz().replace(tzinfo=None).isoformat(),
              'end_clock': end.timetz().replace(tzinfo=None).isoformat(),
              'end_day_offset': (end.date() - start.date()).days}
    if result['repeat']['frequency'] == 'weekly' and start.isoweekday() not in result['repeat']['weekdays']:
        raise ValueError('首轮开始日期不在指定星期中')
    if result['repeat']['until'] and result['repeat']['until'] < result['anchor_date']:
        raise ValueError('重复截止日期早于首轮')
    if result['repeat']['count'] is not None and result['repeat']['count'] <= anchor_index:
        raise ValueError('总次数已被之前轮次用尽')
    # Every weekly gap appears within one pass through the selected weekdays.
    # Compare civil endpoints, so the check also covers later DST transitions.
    remaining = result['repeat']['count']
    if result['repeat']['until']:
        remaining = first_index_at_or_after(result, date.fromisoformat(result['repeat']['until']) + timedelta(days=1))
    pairs = 1 if result['repeat']['frequency'] == 'daily' else len(result['repeat']['weekdays'])
    if remaining is not None:
        pairs = min(pairs, remaining - anchor_index - 1)
    for offset in range(max(0, pairs)):
        day = date_for_index(result, anchor_index + offset)
        next_day = date_for_index(result, anchor_index + offset + 1)
        if datetime.combine(day + timedelta(days=result['end_day_offset']), time.fromisoformat(result['end_clock'])) > datetime.combine(next_day, time.fromisoformat(result['start_clock'])):
            raise ValueError('相邻循环轮次的时段相互重叠')
    return result


def _count_before(rule, anchor, target):
    days = max(0, (target - anchor).days)
    if rule['frequency'] == 'daily': return days
    full, extra = divmod(days, 7)
    return full * len(rule['weekdays']) + sum((anchor.weekday() + n) % 7 + 1 in rule['weekdays'] for n in range(extra))


def date_for_index(series, index):
    anchor = date.fromisoformat(series['anchor_date'])
    offset = index - series['anchor_index']
    if offset < 0: raise ValueError('轮次早于当前循环规则')
    rule = series['repeat']
    if rule['frequency'] == 'daily': return anchor + timedelta(days=offset)
    lo, hi = 0, (offset + 1) * 7
    while lo < hi:
        mid = (lo + hi) // 2
        if _count_before(rule, anchor, anchor + timedelta(days=mid + 1)) > offset: hi = mid
        else: lo = mid + 1
    return anchor + timedelta(days=lo)


def first_index_at_or_after(series, day):
    anchor = date.fromisoformat(series['anchor_date'])
    return series['anchor_index'] + _count_before(series['repeat'], anchor, max(anchor, day))


def occurrence(series, index):
    rule = series['repeat']
    if rule['count'] is not None and index >= rule['count']: return None
    day = date_for_index(series, index)
    if rule['until'] and day > date.fromisoformat(rule['until']): return None
    zone = ZoneInfo(series['timezone'])
    start = _resolve(day, series['start_clock'], zone)
    end = _resolve(day + timedelta(days=series['end_day_offset']), series['end_clock'], zone)
    # A clock can cross a DST fold; the originally agreed instant still wins
    # for the first occurrence and later occurrences remain civil-time based.
    if end <= start: end = _resolve(day + timedelta(days=series['end_day_offset'] + 1), series['end_clock'], zone)
    return {'start_at': start, 'end_at': end, 'date': day.isoformat(), 'index': index}


def next_occurrence(series, now, consumed):
    zone = ZoneInfo(series['timezone'])
    today = datetime.fromtimestamp(now, zone).date()
    first = max(consumed, first_index_at_or_after(series, today - timedelta(days=series['end_day_offset'] + 1)))
    rule=series['repeat']
    if rule['count'] is not None:first=min(first,rule['count'])
    if rule['until']:
        after_until=first_index_at_or_after(series,date.fromisoformat(rule['until'])+timedelta(days=1))
        first=min(first,after_until)
    skipped = max(0, first - consumed)
    for index in range(first, first + 4):
        item = occurrence(series, index)
        if not item: return None, skipped
        if item['end_at'] > now: return item, skipped
        skipped += 1
    raise RuntimeError('无法计算下一轮预约')


def overlap(a, b):
    return bool(a and b and a['start_at'] < b['end_at'] and b['start_at'] < a['end_at'])


def _effective_end(series):
    rule = series['repeat']
    if rule['count'] is not None: return occurrence(series, rule['count'] - 1)['end_at']
    if rule['until']:
        index = first_index_at_or_after(series, date.fromisoformat(rule['until']) + timedelta(days=1)) - 1
        return occurrence(series, index)['end_at'] if index >= series['anchor_index'] else 0
    return None


def conflict(a, b):
    """Return the first overlapping pair. A schedule may be a single interval or a series."""
    if 'repeat' not in a and 'repeat' not in b:
        return (a, b) if overlap(a, b) else None
    start = max(a['start_at'] if 'repeat' not in a else occurrence(a, a['anchor_index'])['start_at'],
                b['start_at'] if 'repeat' not in b else occurrence(b, b['anchor_index'])['start_at'])
    ends = [v for v in (_effective_end(x) if 'repeat' in x else x['end_at'] for x in (a, b)) if v is not None]
    if ends and min(ends) <= start: return None
    # Two recurring civil-week patterns either meet within a Gregorian 400-year
    # cycle or never meet. Finite schedules narrow that interval further.
    horizon = min(ends) if ends else start + 146097 * 86400
    def items(value):
        if 'repeat' not in value:
            if value['end_at'] > start: yield value
            return
        zone = ZoneInfo(value['timezone'])
        day = datetime.fromtimestamp(start, zone).date() - timedelta(days=value['end_day_offset'] + 1)
        index = max(value['anchor_index'], first_index_at_or_after(value, day))
        while True:
            item = occurrence(value, index)
            if not item or item['start_at'] >= horizon: return
            if item['end_at'] > start: yield item
            index += 1
    left, right = items(a), items(b)
    x, y = next(left, None), next(right, None)
    while x and y:
        if overlap(x, y): return x, y
        if x['end_at'] <= y['end_at']: x = next(left, None)
        else: y = next(right, None)
    return None
