"""Export a synthetic RSI run for the read-only RSI UI.

Run from the repository root: python apps/api/scripts/export_rsi_demo.py [RUN_ID]
The default is the run whose c006 was promoted as probe_planner v003.
Never use this for real student records.
"""
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / 'apps/api/rsi_runs'
DEFAULT_RUN = '20261107-000819-probe_planner'
OUT = ROOT / 'apps/web/rsi-test-assets/rsi-demo.json'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def export(run_id: str = DEFAULT_RUN) -> None:
    run_dir = RUNS / run_id
    run = json.loads(read(run_dir / 'run.json'))
    prompts = {c['id']: read(run_dir / 'candidates' / (c['id'] + '.md')) for c in run['candidates']}
    for c in run['candidates']:
        report = json.loads(read(run_dir / 'candidates' / (c['id'] + '.report.json')))
        c.pop('per_case', None)
        c['prompt'] = prompts[c['id']]
        c['diff'] = ''.join(difflib.unified_diff(prompts[c['parent']].splitlines(True), c['prompt'].splitlines(True), '親の指示文', '候補の指示文')) if c['parent'] else ''
        failures = [f for f in report['report']['failures'] if f['kind'] in ('missed_gap', 'false_alarm', 'guardrail')][:3]
        c['examples'] = [{'failure': f, 'execution': next((n for n in report['notes'] if n['claim'] == f.get('pred_claim')), None)} for f in failures]
        c['violations'] = report['report']['guardrails']['violations']
    OUT.write_text(json.dumps({'run_id': run_dir.name, 'synthetic': True, **run}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    export(*sys.argv[1:2])
