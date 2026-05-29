#!/usr/bin/env hy

(import subprocess)
(import tempfile)
(import husks.build [build rule action oracle trial])
(import husks.oracle [live_oracle set_oracle_model])

(setv model "anthropic/claude-haiku-4-5-20251001")
(set_oracle_model model)

(setv cse-test-source
  (+ "import importlib.util\n"
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
     "assert mini_cse.parse(b'()') == []\n"
     "assert mini_cse.parse(b'(0:)') == [b'']\n"
     "assert mini_cse.parse(b'(4:husk3:cse)') == [b'husk', b'cse']\n"
     "assert mini_cse.parse(b'((1:a)(1:b1:c))') == [[b'a'], [b'b', b'c']]\n"
     "\n"
     "must_fail(b'')\n"
     "must_fail(b':abc')\n"
     "must_fail(b'04:husk')\n"
     "must_fail(b'4x:husk')\n"
     "must_fail(b'5:husk')\n"
     "must_fail(b'4:huskx')\n"
     "must_fail(b'1:a1:b')\n"
     "must_fail(b'(4:husk')\n"
     "must_fail(b'(1:a))')\n"
     "must_fail(b')')\n"))

(defn write-spec [S]
  (let [site (get S "site")
        path (+ site "/cse-mini-spec.txt")
        text (+ "Implement a tiny Canonical S-expression reader in Python.\n"
                "\n"
                "Encoding rules:\n"
                "1. An atom is encoded as decimal length, colon, raw bytes.\n"
                "2. A list starts with byte '(' and ends with byte ')'.\n"
                "3. Lists contain zero or more CSE values.\n"
                "4. Length prefixes must contain only digits.\n"
                "5. Empty length prefixes are invalid.\n"
                "6. Leading zeroes are invalid except for the atom length 0.\n"
                "7. Atom payload length must match the prefix exactly.\n"
                "8. The parser must reject trailing bytes after one complete value.\n"
                "\n"
                "Required API:\n"
                "  parse(data: bytes) -> nested Python value\n"
                "\n"
                "Representation:\n"
                "  atoms are returned as bytes\n"
                "  lists are returned as Python lists\n")]
    (with [f (open path "w")]
      (.write f text))))

(defn write-tests [S]
  (let [site (get S "site")
        path (+ site "/test_mini_cse.py")]
    (with [f (open path "w")]
      (.write f cse-test-source))))

(defn named [recipe name]
  (.update recipe {"name" name})
  recipe)

(defn score-candidate [code]
  (with [d (tempfile.TemporaryDirectory)]
    (let [reader-path (+ d "/mini_cse.py")
          test-path (+ d "/test_mini_cse.py")]
      (with [f (open reader-path "w")]
        (.write f code))
      (with [f (open test-path "w")]
        (.write f cse-test-source))
      (let [result (subprocess.run ["python" "test_mini_cse.py"]
                                   :cwd d
                                   :text True
                                   :capture_output True)]
        (if (= result.returncode 0)
            1
            0)))))

(defn choose-best [results]
  (let [best None
        best-score -1]
    (for [r results]
      (let [outputs (.get r "outputs" {})
            code (.get outputs "mini_cse.py" "")
            score (if code (score-candidate code) 0)]
        (when (> score best-score)
          (setv best r)
          (setv best-score score))))
    (when (or (is best None) (= best-score 0))
      (raise (Exception "trial failed: no branch passed conformance tests")))
    {"winner" best}))

(defn verify-winner [S]
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
            :recipe (action write-tests))

      branch-a
      (named
        (oracle "claude-haiku-cse-reader-a"
                :prompt (+ "Read cse-mini-spec.txt and test_mini_cse.py. "
                           "Create exactly one file: mini_cse.py. "
                           "Use a small recursive-descent parser. "
                           "Reject malformed canonical encodings. "
                           "Use the write-file tool. "
                           "Do not write markdown. "
                           "Do not explain.")
                :tools ["read-file" "write-file"]
                :fuel 8)
        "reader-a")

      branch-b
      (named
        (oracle "claude-haiku-cse-reader-b"
                :prompt (+ "Read cse-mini-spec.txt and test_mini_cse.py. "
                           "Create exactly one file: mini_cse.py. "
                           "Use an iterative parser if useful. "
                           "Pay special attention to trailing data, leading zeroes, "
                           "non-digit length prefixes, empty lists, and nested lists. "
                           "Use the write-file tool. "
                           "Do not write markdown. "
                           "Do not explain.")
                :tools ["read-file" "write-file"]
                :fuel 8)
        "reader-b")

      picked-reader
      (rule "trial-cse-reader"
            spec
            tests
            :inputs ["cse-mini-spec.txt" "test_mini_cse.py"]
            :outputs ["mini_cse.py"]
            :recipe (trial branch-a branch-b :verdict choose-best))

      verify
      (rule "verify-picked-reader"
            picked-reader
            :inputs ["mini_cse.py" "test_mini_cse.py"]
            :outputs ["test-report.txt"]
            :recipe (action verify-winner))

      S
      (build "claude-haiku-trial-cse-demo"
             24
             verify
             :site ".husks-trial-cse-site"
             :oracle_backend live_oracle
             :oracle_model model)]

  (print "status:" (get S "status"))
  (print "site:" (get S "site"))
  (print "root:" (get S "build-root")))
