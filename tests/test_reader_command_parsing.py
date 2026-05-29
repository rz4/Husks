"""
test_reader_command_parsing.py -- Tests for Beta B6 reader command parsing.

Beta Gate B6: Use shlex.split() for reader commands.

Validates that reader commands are parsed correctly with quoted arguments.
"""

import shlex


def test_simple_reader_command():
    """Simple reader commands are parsed correctly."""
    cmd = "python reader.py"
    result = shlex.split(cmd)
    assert result == ["python", "reader.py"]


def test_reader_command_with_args():
    """Reader commands with arguments are parsed correctly."""
    cmd = "python reader.py --verbose --output file.txt"
    result = shlex.split(cmd)
    assert result == ["python", "reader.py", "--verbose", "--output", "file.txt"]


def test_reader_command_with_quoted_arg():
    """Reader commands with quoted arguments preserve spaces."""
    cmd = "python reader.py --message 'hello world'"
    result = shlex.split(cmd)
    assert result == ["python", "reader.py", "--message", "hello world"]


def test_reader_command_with_quoted_path():
    """Reader commands with quoted paths containing spaces work."""
    cmd = "python '/path/with spaces/reader.py' --arg value"
    result = shlex.split(cmd)
    assert result == ["python", "/path/with spaces/reader.py", "--arg", "value"]


def test_reader_command_with_double_quotes():
    """Reader commands work with double quotes."""
    cmd = 'python reader.py --message "hello world"'
    result = shlex.split(cmd)
    assert result == ["python", "reader.py", "--message", "hello world"]


def test_reader_command_with_escaped_quotes():
    """Reader commands with escaped quotes in double-quoted strings work."""
    # In shell syntax, you can escape quotes inside double quotes
    cmd = 'python reader.py --message "it\'s working"'
    result = shlex.split(cmd)
    assert result == ["python", "reader.py", "--message", "it's working"]


def test_reader_command_regression_simple_split():
    """Regression: simple .split() would fail with quoted arguments."""
    # Old way (would incorrectly split quoted args)
    cmd = "python reader.py --message 'hello world'"
    old_result = cmd.split()

    # New way (correctly handles quotes)
    new_result = shlex.split(cmd)

    # Demonstrate the difference
    assert old_result == ["python", "reader.py", "--message", "'hello", "world'"]
    assert new_result == ["python", "reader.py", "--message", "hello world"]
    assert old_result != new_result


def test_reader_command_complex_example():
    """Complex reader command with multiple quoted arguments."""
    cmd = 'python "/usr/bin/my reader.py" --input "file with spaces.txt" --format json'
    result = shlex.split(cmd)
    assert result == [
        "python",
        "/usr/bin/my reader.py",
        "--input",
        "file with spaces.txt",
        "--format",
        "json",
    ]
