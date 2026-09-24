"""Split the time between two samples into observed and unknown portions."""


def split_interval(previous, current, default_interval):
    elapsed = current['mono'] - previous['mono']
    if elapsed <= 0:
        return 0.0, max(abs(elapsed), 0.001)
    interval = previous.get('settings', {}).get('sampling', {}).get('interval_seconds', default_interval)
    observed = min(elapsed, max(3.0, interval * 1.5))
    return observed, elapsed - observed
