"""Run the composite action's real shell against an offline audit process."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ACTION = (Path(__file__).resolve().parents[1] / 'action.yml').read_text()


def step_script(name):
    block = ACTION.split(f'    - name: {name}\n', 1)[1].split('\n    - name:', 1)[0]
    script = block.split('      run: |\n', 1)[1]
    script = '\n'.join(line[8:] for line in script.splitlines())
    script = script.replace('${{ github.event_name }}', 'pull_request')
    script = script.replace('${{ steps.claudecode-history.outputs.cache-hit }}', '')
    return script


@pytest.fixture
def action_env(tmp_path):
    action = tmp_path / 'action source'
    workspace = tmp_path / 'PR workspace'
    binaries = tmp_path / 'bin'
    (action / 'claudecode').mkdir(parents=True)
    workspace.mkdir()
    binaries.mkdir()
    # Only the audit process is faked; the action's validation/copy/exit code runs.
    shim = binaries / 'python'
    shim.write_text(f'''#!{sys.executable}
import os, pathlib, sys
if sys.argv[1:3] == ['-u', 'claudecode/github_action_audit.py']:
    sys.stderr.write('fixture audit diagnostics\\n')
    if os.environ.get('REMOVE_RESULT') == 'true':
        pathlib.Path('claudecode/claudecode-results.json').unlink()
    sys.stdout.write(os.environ['AUDIT_RESULT'])
    sys.exit(int(os.environ['AUDIT_EXIT']))
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')
    shim.chmod(0o755)
    env = dict(os.environ, PATH=f'{binaries}:{os.environ["PATH"]}',
               ACTION_PATH=str(action), GITHUB_WORKSPACE=str(workspace),
               GITHUB_OUTPUT=str(tmp_path / 'outputs'), ANTHROPIC_API_KEY='fixture',
               CLAUDECODE_TIMEOUT='1', PYTHONPATH='', GITHUB_REPOSITORY='fixture/repo',
               PR_NUMBER='1', RUN_EVERY_COMMIT='false', AUDIT_EXIT='0', AUDIT_RESULT='')
    return env


def run_step(name, env):
    return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c', step_script(name)],
                          cwd=env['GITHUB_WORKSPACE'], env=env, text=True, capture_output=True)


@pytest.mark.parametrize('payload,exit_code,remove', [
    ('{"error":"API Error: 400 unknown model"}', 1, False),
    ('{"error":"timeout","findings":[]}', 0, False),
    ('{"findings":[]}', 124, False),
    ('', 0, False),
    ('not json', 0, False),
    ('{}', 0, False),
    ('{"findings":null}', 0, False),
    ('{"findings":{}}', 0, False),
    ('{"findings":[null]}', 0, False),
    ('{"findings":[]}\n{"findings":[]}', 0, False),
    ('', 0, True),
])
def test_failed_scan_is_not_clean_success(action_env, payload, exit_code, remove):
    env = dict(action_env, AUDIT_RESULT=payload, AUDIT_EXIT=str(exit_code), REMOVE_RESULT=str(remove).lower())
    # Both locations may contain output left over from another backend attempt.
    for directory in [env['ACTION_PATH'], env['GITHUB_WORKSPACE']]:
        (Path(directory) / 'findings.json').write_text('[{"severity":"HIGH"}]')
    result = run_step('Run ClaudeCode scan', env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (Path(env['GITHUB_WORKSPACE']) / 'findings.json').exists()
    assert 'findings_count=' not in Path(env['GITHUB_OUTPUT']).read_text()
    assert (Path(env['GITHUB_WORKSPACE']) / 'claudecode-error.log').read_text() == 'fixture audit diagnostics\n'
    if not remove:
        assert (Path(env['GITHUB_WORKSPACE']) / 'claudecode-results.json').read_text() == payload


@pytest.mark.parametrize('findings', [[], [{'file': 'auth.py', 'severity': 'HIGH', 'description': 'SQL injection'}]])
def test_completed_scan_publishes_results(action_env, findings):
    env = dict(action_env, AUDIT_RESULT=json.dumps({'findings': findings}))
    result = run_step('Run ClaudeCode scan', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((Path(env['GITHUB_WORKSPACE']) / 'findings.json').read_text()) == findings
    assert f'findings_count={len(findings)}\n' in Path(env['GITHUB_OUTPUT']).read_text()


@pytest.mark.parametrize('marker,enabled', [(None, True), ('reserved', True), ('completed', False), ('invalid', True)])
def test_only_completed_scan_can_suppress_retry(action_env, marker, enabled):
    env = action_env
    if marker is not None:
        path = Path(env['GITHUB_WORKSPACE']) / '.claudecode-marker/marker.json'
        path.parent.mkdir()
        path.write_text('not json' if marker == 'invalid' else json.dumps({'status': marker}))
    result = run_step('Determine ClaudeCode enablement', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'enable_claudecode={str(enabled).lower()}\n' in Path(env['GITHUB_OUTPUT']).read_text()


def test_failed_primary_can_run_successful_fallback(action_env):
    env = dict(action_env, AUDIT_RESULT='{"error":"unknown model"}', AUDIT_EXIT='1')
    assert run_step('Run ClaudeCode scan', env).returncode == 1
    assert run_step('Determine ClaudeCode enablement', env).returncode == 0
    assert 'enable_claudecode=true\n' in Path(env['GITHUB_OUTPUT']).read_text()
    env.update(AUDIT_RESULT='{"findings":[]}', AUDIT_EXIT='0')
    assert run_step('Run ClaudeCode scan', env).returncode == 0
    assert json.loads((Path(env['GITHUB_WORKSPACE']) / 'findings.json').read_text()) == []


def test_local_action_workspace_can_equal_action_path(action_env):
    env = dict(action_env, GITHUB_WORKSPACE=action_env['ACTION_PATH'], AUDIT_RESULT='{"findings":[]}')
    result = run_step('Run ClaudeCode scan', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((Path(env['GITHUB_WORKSPACE']) / 'findings.json').read_text()) == []


def test_completed_scan_marker_allows_later_skip(action_env):
    env = dict(action_env, AUDIT_RESULT='{"findings":[]}', REPOSITORY_ID='1',
               REPOSITORY='fixture/repo', SHA='fixture-sha', RUN_ID='1', RUN_NUMBER='1')
    assert run_step('Run ClaudeCode scan', env).returncode == 0
    assert run_step('Record completed ClaudeCode scan', env).returncode == 0
    result = run_step('Determine ClaudeCode enablement', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'enable_claudecode=false\n' in Path(env['GITHUB_OUTPUT']).read_text()
