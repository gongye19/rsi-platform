#!/usr/bin/env python3
"""Run the local API, worker and built frontend. No model requests at startup."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harnesslens.service.config import profile_environment
from harnesslens.service.worker import process_identity, stop_owned
from harnesslens.core.model_config import without_credentials


def occupied(port):
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', port)) == 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-port', type=int, default=3210)
    parser.add_argument('--api-port', type=int, default=8765)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'runs/platform'
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / 'processes.json'
    processes = json.loads(receipt.read_text()) if receipt.is_file() else {}
    alive = {k: v for k, v in processes.items() if process_identity(v['pid']) == v['identity']}
    if args.stop:
        for row in reversed(list(alive.values())): stop_owned(row['pid'], row['identity'])
        receipt.unlink(missing_ok=True)
        print('Local platform stopped. Experiment evidence is retained.')
        return
    for role, port in [('api', args.api_port), ('web', args.web_port)]:
        if role in alive and alive[role].get('port') != port:
            raise SystemExit('Stop the local platform before changing ports.')
        if occupied(port) and (role not in alive or alive[role].get('port') != port):
            raise SystemExit(f'Port {port} belongs to another service. Choose a different port.')
    env_path = ROOT / '.env'
    env = profile_environment({'env_file': str(env_path) if env_path.is_file() else '', 'environment': {}})
    token = env.get('HAI_SERVICE_TOKEN', '')
    if len(token) < 24:
        token = secrets.token_urlsafe(32)
        lines = env_path.read_text().splitlines() if env_path.is_file() else []
        env_path.write_text('\n'.join(line for line in lines if not line.startswith('HAI_SERVICE_TOKEN=')) + '\nHAI_SERVICE_TOKEN=' + token + '\n')
        env_path.chmod(0o600)
    env['HAI_SERVICE_TOKEN'] = token
    url = f'http://127.0.0.1:{args.api_port}'
    # This file is server-only and ignored by git; no model credentials enter it.
    web_env = ROOT / 'web/.env.local'
    existing = web_env.read_text().splitlines() if web_env.is_file() else []
    web_env.write_text('\n'.join(line for line in existing if not line.startswith(('HARNESSLENS_API_URL=', 'HAI_SERVICE_TOKEN='))) + f'\nHARNESSLENS_API_URL={url}\nHAI_SERVICE_TOKEN={token}\n')
    web_env.chmod(0o600)
    node = shutil.which('node')
    if not node or not (ROOT / 'web/.next/BUILD_ID').is_file():
        raise SystemExit('Build the frontend first: cd web && bun install --frozen-lockfile && bun run build')
    commands = {
        'api': ([sys.executable, '-m', 'harnesslens.service', 'api', '--port', str(args.api_port)], ROOT, env, args.api_port),
        'worker': ([sys.executable, '-m', 'harnesslens.service', 'worker'], ROOT, env, None),
        'web': ([node, 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', str(args.web_port)], ROOT / 'web',
                {**without_credentials(env), 'HAI_SERVICE_TOKEN': token, 'HARNESSLENS_API_URL': url}, args.web_port),
    }
    started = []
    try:
        for role, (command, cwd, role_env, port) in commands.items():
            if role in alive: continue
            with (directory / (role + '.log')).open('a') as log:
                process = subprocess.Popen(command, cwd=cwd, env=role_env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            identity = process_identity(process.pid)
            alive[role] = {'pid': process.pid, 'identity': identity, 'port': port}
            started.append(role)
            receipt.write_text(json.dumps(alive, indent=2) + '\n')
        for endpoint in [url + '/health', f'http://127.0.0.1:{args.web_port}/experiments']:
            deadline = time.monotonic() + 25
            while True:
                try:
                    with urllib.request.urlopen(endpoint, timeout=2) as response:
                        if response.status == 200: break
                except OSError:
                    if time.monotonic() >= deadline: raise RuntimeError('Platform startup failed; inspect runs/platform/*.log')
                    time.sleep(.2)
    except BaseException:
        for role in reversed(started):
            row = alive.pop(role)
            stop_owned(row['pid'], row['identity'])
        receipt.write_text(json.dumps(alive, indent=2) + '\n')
        raise
    print(f'Frontend: http://127.0.0.1:{args.web_port}/experiments')
    print('API and worker are running. Logs: runs/platform. Stop: python scripts/start_local_platform.py --stop')


if __name__ == '__main__': main()
