import importlib.util
from pathlib import Path

p = Path(__file__).parent / 'mini_cse.py'
spec = importlib.util.spec_from_file_location('mini_cse', p)
mini_cse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mini_cse)

def must_fail(data):
    try:
        mini_cse.parse(data)
    except Exception:
        return
    raise AssertionError(f'should have rejected {data!r}')

# Weak public tests. The cheat branch is designed to pass these.
assert mini_cse.parse(b'4:husk') == b'husk'
assert mini_cse.parse(b'0:') == b''
assert mini_cse.parse(b'()') == []
must_fail(b'5:husk')
