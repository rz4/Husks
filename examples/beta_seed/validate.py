#!/usr/bin/env python3
"""Beta seed validator (Task 5/Gate E).

Validates that oracle output conforms to deterministic output contract:
- MUST start with "ANSWER: "
- For live oracle: answer should be "Paris" (capital of France)
- For stub oracle: answer should be stub placeholder text
- Fails on malformed output (no ANSWER: prefix, empty, wrong format)
"""

import re
import sys


def validate_response(response_text: str) -> tuple[bool, str]:
    """Validate response against structured output contract.

    Returns:
        (valid, message) where valid is True if response passes validation
    """
    response_text = response_text.strip()

    if not response_text:
        return False, "FAIL: Empty response"

    # Task 5: Require structured format "ANSWER: <answer>" (single line only)
    # Use MULTILINE mode but NOT DOTALL, so .+ matches only up to newline
    match = re.match(r'^ANSWER:\s*(.+?)(?:\n|$)', response_text, re.IGNORECASE | re.MULTILINE)

    if not match:
        return False, f"FAIL: Expected 'ANSWER: <answer>' format, got: {response_text[:50]}"

    answer = match.group(1).strip()

    # Accept correct live answer or stub placeholder
    valid_answers = {
        'paris',  # Correct answer for "capital of France"
    }

    # Also accept stub oracle placeholders (case-insensitive)
    is_stub = any(stub_marker in answer.lower() for stub_marker in [
        'stub oracle output',
        'oracle output placeholder',
        'stub output',
    ])

    if answer.lower() in valid_answers or is_stub:
        return True, "PASS"
    else:
        return False, f"FAIL: Invalid answer '{answer}' (expected 'Paris' or stub placeholder)"


def main():
    try:
        with open('response.txt', 'r') as f:
            response = f.read()

        valid, message = validate_response(response)

        with open('validation.txt', 'w') as f:
            f.write(message + '\n')

        # Exit 0 for pass, 1 for fail (action rule will halt build on failure)
        sys.exit(0 if valid else 1)

    except FileNotFoundError:
        with open('validation.txt', 'w') as f:
            f.write('FAIL: response.txt not found\n')
        sys.exit(1)
    except Exception as e:
        with open('validation.txt', 'w') as f:
            f.write(f'FAIL: Validation error: {e}\n')
        sys.exit(1)


if __name__ == '__main__':
    main()
