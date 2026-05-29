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

assert mini_cse.parse(b'4:husk') == b'husk'
assert mini_cse.parse(b'0:') == b''
assert mini_cse.parse(b'()') == []
assert mini_cse.parse(b'(0:)') == [b'']
assert mini_cse.parse(b'(4:husk3:cse)') == [b'husk', b'cse']
assert mini_cse.parse(b'((1:a)(1:b1:c))') == [[b'a'], [b'b', b'c']]

must_fail(b'')
must_fail(b':abc')
must_fail(b'04:husk')
must_fail(b'4x:husk')
must_fail(b'5:husk')
must_fail(b'4:huskx')
must_fail(b'1:a1:b')
must_fail(b'(4:husk')
must_fail(b'(1:a))')
must_fail(b')')
