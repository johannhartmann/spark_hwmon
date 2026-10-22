#!/usr/bin/env python3
"""Reproduce the short CPU/CUDA workload used in the committed captures.

Run as the ordinary desktop user, alongside capture-n1x.py in another terminal.
The GPU phase calls an already running CUDA llama.cpp server on localhost:8080,
with model alias p16-local. This does not configure or start that server.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def run(capture, phase_file, events_file):
    if os.geteuid() == 0:
        raise ValueError('Run workloads as the ordinary desktop user')
    # Refuse an existing result path before starting any workloads.
    with events_file.open('x') as output:
        events = []
        processes = []
        requests = tokens = 0
        failure = None
        def mark(name):
            phase_file.write_text(name)
            events.append({'phase': name, 'monotonic': time.monotonic()})
            print(name, flush=True)
        try:
            deadline = time.monotonic() + 90
            while not capture.exists() or capture.stat().st_size < 20:
                if time.monotonic() > deadline:
                    raise TimeoutError('Capture did not start within 90 seconds')
                time.sleep(.2)
            if time.time() - capture.stat().st_mtime > 5:
                raise ValueError('Capture is stale; start a fresh active capture first')
            mark('idle')
            time.sleep(5)
            mark('cpu')
            code = ('import hashlib,time; d=b"x"*131072; end=time.monotonic()+12;\n'
                    'while time.monotonic()<end: hashlib.sha256(d).digest()')
            for _ in range(8):
                processes.append(subprocess.Popen([sys.executable, '-c', code]))
            for process in processes:
                if process.wait() != 0:
                    raise RuntimeError('CPU worker failed')
            mark('recovery')
            time.sleep(5)
            mark('gpu')
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
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
            mark('cooldown')
            time.sleep(5)
        except BaseException as error:
            failure = str(error)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
            record = {'events': events, 'gpu_requests': requests,
                      'gpu_completion_tokens': tokens, 'cpu_processes': len(processes)}
            if failure is not None:
                record['error'] = failure
            json.dump(record, output, indent=2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('phase_file', type=Path)
    parser.add_argument('events_file', type=Path)
    args = parser.parse_args()
    try:
        run(args.capture, args.phase_file, args.events_file)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
