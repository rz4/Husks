import importlib.util
from pathlib import Path

p = Path(__file__).parent / 'answer.py'
spec = importlib.util.spec_from_file_location('answer', p)
answer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(answer)

assert answer.normalize_slug('Hello, Husks!') == 'hello-husks'
assert answer.normalize_slug('  Build---Residue  ') == 'build-residue'
assert answer.normalize_slug('A/B/C') == 'a-b-c'
assert answer.normalize_slug('already-clean') == 'already-clean'
assert answer.normalize_slug('...') == ''
