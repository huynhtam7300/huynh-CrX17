import time

def retry(fn, tries=3, delay=0.5):
    for i in range(tries):
        try:
            return fn()
        except Exception:
            time.sleep(delay)
    return None