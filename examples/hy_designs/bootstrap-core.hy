#!/usr/bin/env hy
"""Bootstrap-core: generate a CSE reader and gate it.

Hy equivalent of bootstrap-core.json.  Uses action args to keep the
gate rule generic.

Usage:
    hy examples/bootstrap-core.hy
"""

;-
(import os shutil subprocess)
(import husks.build [build rule action oracle site_path write_text ensure_dir])
(import husks.oracle [live_oracle set_oracle_model])
(require husks.macros [defaction deforacle]
         hyrule [->])

(set_oracle_model "anthropic/claude-haiku-4-5-20251001")

;--
(defaction stage-files [#* files]
  (for [f files]
    (let [dest (site_path S f)]
      (ensure_dir (os.path.dirname dest))
      (shutil.copy f dest))))


(defaction run-gate [cmd report-file]
  (let [site (get S "site")
        result (subprocess.run (.split cmd)
                               :cwd site :text True :capture_output True)]
    (write_text (site_path S report-file) result.stdout)
    (when (!= result.returncode 0)
      (raise (Exception (+ "gate failed: " result.stderr))))))

;--
(deforacle generate-reader
  :prompt (+ "Read CSE-v1.md (the frozen spec) and CSE-v2.md (clarifications with worked examples). "
             "Implement a dependency-free CSE reader in a single Python file at readers/generated_reader.py. "
             "Constraints: use ONLY the Python standard library, and ONLY hashlib, sys, os. "
             "Do NOT use json, re, ast, pickle, or any parsing library. "
             "Write a byte-level netstring parser: read the decimal length prefix, "
             "then a colon, then exactly that many raw bytes. Reject leading zeros in a length "
             "(e.g. 05:hello is invalid). Reject an atom whose declared length exceeds the remaining bytes. "
             "Implement the seal preimage, recipe digest, output bindings, and Merkle node digest exactly "
             "as specified, using SHA-256 and lowercase hex. Critical: children of a rule are the CSE values "
             "at positions 5+ in the parsed rule list — recurse into them in positional order. Do NOT match "
             "children against input filenames. All intermediate digests (recipe-digest, seal, child digests) "
             "are 64-byte lowercase hex string atoms, not raw 32-byte hashes. Command-line contract: `python "
             "generated_reader.py <husk-file> <site-dir>` must print the lowercase-hex build-root to stdout "
             "and exit 0; on any CSE violation it must exit with a nonzero status. Write only readers/generated_reader.py.")
  :tools ["read-file" "write-file"]
  :fuel 8)

;---
(build
  :name "bootstrap-core"
  :fuel 12
  :site ".husks-bootstrap-core-site"
  :oracle_backend live_oracle

  (-> (rule :name "stage-inputs"
            :recipe (stage-files "spec/CSE-v1.md" "spec/CSE-v2.md")
            :outputs ["CSE-v1.md" "CSE-v2.md"])

      (rule :name "generate-reader"
            :inputs ["CSE-v1.md" "CSE-v2.md"]
            :recipe (generate-reader)
            :outputs ["readers/generated_reader.py"])

      (rule :name "gate"
            :inputs ["readers/generated_reader.py"]
            :recipe (run-gate
                      "husks-gate python readers/generated_reader.py --stamp-dir readers"
                      "readers/gate-report.txt")
            :outputs ["readers/gate-report.txt" "readers/VERIFIED"])))

