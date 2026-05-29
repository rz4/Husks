#!/usr/bin/env hy

(import subprocess)
(import husks.build [build rule action oracle])
(import husks.oracle [live_oracle set_oracle_model])

(setv model "anthropic/claude-haiku-4-5-20251001")
(set_oracle_model model)

(defn write-spec [S]
  (let [site (get S "site")
        path (+ site "/cse-mini-spec.txt")
        text (+ "Implement a tiny Canonical S-expression reader in Python.\n"
                "\n"
                "Encoding rules:\n"
                "1. An atom is encoded as decimal length, colon, raw bytes.\n"
                "2. A list starts with byte '(', contains zero or more CSE values, and ends with byte ')'.\n"
                "3. Length prefixes must contain only digits.\n"
                "4. Empty length prefixes are invalid.\n"
                "5. Leading zeroes are invalid except for the atom length 0.\n"
                "6. Atom payload length must match the prefix exactly.\n"
                "7. The parser must reject trailing bytes after one complete value.\n"
                "\n"
                "Required API:\n"
                "  parse(data: bytes) -> nested Python value\n"
                "\n"
                "Representation:\n"
                "  atoms are returned as bytes\n"
                "  lists are returned as Python lists\n")]
    (with [f (open path "w")]
      (.write f text))))

(defn write-test [S]
  (let [site (get S "site")
        path (+ site "/test_mini_cse.py")
        text (+ "import importlib.util\n"
                "from pathlib import Path\n"
                "\n"
                "p = Path(__file__).parent / 'mini_cse.py'\n"
                "spec = importlib.util.spec_from_file_location('mini_cse', p)\n"
                "mini_cse = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(mini_cse)\n"
                "\n"
                "def must_fail(data):\n"
                "    try:\n"
                "        mini_cse.parse(data)\n"
                "    except Exception:\n"
                "        return\n"
                "    raise AssertionError(f'should have rejected {data!r}')\n"
                "\n"
                "assert mini_cse.parse(b'4:husk') == b'husk'\n"
                "assert mini_cse.parse(b'0:') == b''\n"
                "assert mini_cse.parse(b'(4:husk3:cse)') == [b'husk', b'cse']\n"
                "assert mini_cse.parse(b'((1:a)(1:b1:c))') == [[b'a'], [b'b', b'c']]\n"
                "\n"
                "must_fail(b'')\n"
                "must_fail(b':abc')\n"
                "must_fail(b'04:husk')\n"
                "must_fail(b'4x:husk')\n"
                "must_fail(b'5:husk')\n"
                "must_fail(b'4:huskx')\n"
                "must_fail(b'(4:husk')\n"
                "must_fail(b')')\n")]
    (with [f (open path "w")]
      (.write f text))))

(defn verify-reader [S]
  (let [site (get S "site")
        report (+ site "/test-report.txt")
        result (subprocess.run ["python" "test_mini_cse.py"]
                               :cwd site
                               :text True
                               :capture_output True)]
    (with [f (open report "w")]
      (.write f (+ "returncode: " (str result.returncode) "\n\n"))
      (.write f "stdout:\n")
      (.write f result.stdout)
      (.write f "\n\nstderr:\n")
      (.write f result.stderr))
    (when (!= result.returncode 0)
      (raise (Exception "verification failed")))))

(let [spec
      (rule "write-cse-spec"
            :outputs ["cse-mini-spec.txt"]
            :recipe (action write-spec))

      tests
      (rule "write-cse-tests"
            :outputs ["test_mini_cse.py"]
            :recipe (action write-test))

      reader
      (rule "write-mini-cse-reader"
            spec
            tests
            :inputs ["cse-mini-spec.txt" "test_mini_cse.py"]
            :outputs ["mini_cse.py"]
            :recipe
            (oracle "claude-haiku-cse-reader"
                    :prompt (+ "Read cse-mini-spec.txt and test_mini_cse.py. "
                               "Create exactly one file: mini_cse.py. "
                               "Use the write-file tool. "
                               "Do not write markdown. "
                               "Do not explain. "
                               "The implementation must pass test_mini_cse.py.")
                    :tools ["read-file" "write-file"]
                    :fuel 8))

      verify
      (rule "verify-mini-cse-reader"
            reader
            :inputs ["mini_cse.py" "test_mini_cse.py"]
            :outputs ["test-report.txt"]
            :recipe (action verify-reader))

      S
      (build "claude-haiku-cse-reader-demo"
             16
             verify
             :site ".husks-cse-reader-site"
             :oracle_backend live_oracle
             :oracle_model model)]

  (print "status:" (get S "status"))
  (print "site:" (get S "site"))
  (print "root:" (get S "build-root")))
