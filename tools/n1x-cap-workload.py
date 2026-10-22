#!/usr/bin/env python3
"""Normal-user P-core load, optionally CUDA inference, for cap experiments.

The GPU option requires the existing localhost:8080 p16-local model server.
No CPU governor, profile, model server or hardware register is changed here.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def run(capture, gpu=False, long_window=False):
    if os.geteuid() == 0:
        raise ValueError('Run as the normal user')
    duration = 105 if long_window else 45
    output = capture.with_name(capture.stem + '-workload.json')
    # Reserve the result before starting workloads, without replacing old evidence.
    with output.open('x') as stream:
        deadline = time.monotonic() + 60
        while not capture.exists() or capture.stat().st_size < 40:
            if time.monotonic() > deadline:
                raise TimeoutError('No fresh control capture')
            time.sleep(.1)
        if time.time() - capture.stat().st_mtime >= 5:
            raise ValueError('Capture is stale')
        cpus = [cpu for cpu in sorted(os.sched_getaffinity(0))
                if (int(Path(f'/sys/devices/system/cpu/cpu{cpu}/regs/identification/midr_el1')
                        .read_text(), 16) >> 4) & 0xfff == 0xd85]
        if len(cpus) != 10:
            raise ValueError('Expected ten Cortex-X925 P cores')
        code = ('import os,sys,time,hashlib; c=int(sys.argv[1]); '
                'os.sched_setaffinity(0,{c}); assert os.sched_getaffinity(0)=={c}; '
                'end=time.monotonic()+float(sys.argv[2]); d=b"x"*131072;\n'
                'while time.monotonic()<end: hashlib.sha256(d).digest()')
        children = []
        requests = tokens = 0
        start = time.monotonic()
        failure = None
        try:
            children = [subprocess.Popen([sys.executable, '-c', code, str(cpu), str(duration)])
                        for cpu in cpus]
            print('Pinned P-core workers active:', cpus, flush=True)
            if gpu:
                while time.monotonic() - start < duration:
                    body = json.dumps({'model': 'p16-local', 'messages': [
                        {'role': 'user', 'content': 'Write integers from 1 to 1000, separated by spaces.'}],
                        'max_tokens': 128, 'temperature': 0}).encode()
                    request = urllib.request.Request(
                        'http://127.0.0.1:8080/v1/chat/completions', data=body,
                        headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(request, timeout=20) as response:
                        result = json.load(response)
                    requests += 1
                    tokens += result.get('usage', {}).get('completion_tokens', 0)
            for child in children:
                if child.wait() != 0:
                    raise RuntimeError('P-core worker failed')
        except BaseException as error:
            failure = str(error)
            raise
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.wait()
            record = {'start_monotonic': start, 'end_monotonic': time.monotonic(),
                      'p_cpus': cpus, 'gpu_requests': requests, 'completion_tokens': tokens}
            if failure is not None:
                record['error'] = failure
            json.dump(record, stream, indent=2)
        print('Workers stopped', record)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--long', action='store_true', dest='long_window')
    args = parser.parse_args()
    run(args.capture, args.gpu, args.long_window)
