#!/usr/bin/env hy
;; build.hy — nine-form build system (v2)
;;
;; Forms:  build  rule  let  cond  action  oracle  trial  commit  halt
;;
;; Nesting is dependency.  The s-expression IS the DAG.
;; The model is an oracle — a non-deterministic recipe whose
;; internals the build never inspects.  It checks the residue.
;;
;; v2: rich seal format (per-input hashes), staleness reasons,
;;     diamond annotations, trial scores, artifact manifest.

(import json hashlib shutil tempfile uuid time)
(import pathlib [Path])
(import husks.trace :as T)


;; ═══════════════════════════════════════════════════════════════
;; Stop signal
;; ═══════════════════════════════════════════════════════════════

(defclass Stop [Exception]
  (defn __init__ [self kind value]
    (setv self.kind kind self.value value)
    (.__init__ (super))))


;; ═══════════════════════════════════════════════════════════════
;; Store helpers
;; ═══════════════════════════════════════════════════════════════

(defn site-path [S name]
  (str (/ (Path (get S "site")) name)))

(defn ensure-dir [p]
  (.mkdir (Path p) :parents True :exist-ok True) p)

(defn read-text [p]
  (.read-text (Path p)))

(defn write-text [p s]
  (setv pp (Path p))
  (ensure-dir (str pp.parent))
  (.write-text pp (str s)) p)

(defn exists? [p]
  (.exists (Path p)))

(defn fresh-store [site fuel #** kw]
  (ensure-dir site)
  {"site"            site
   "fuel"            fuel
   "status"          "running"
   "value"           None
   "trace"           []
   "oracle-backend"  (.get kw "oracle_backend" None)})


;; ═══════════════════════════════════════════════════════════════
;; Fuel
;; ═══════════════════════════════════════════════════════════════

(defn burn [S label]
  (setv (get S "fuel") (- (get S "fuel") 1))
  (.append (get S "trace") {"event" "burn" "label" label "fuel" (get S "fuel")})
  (when (< (get S "fuel") 0)
    (setv (get S "status") "halted")
    (setv (get S "value") (+ "fuel exhausted: " label))
    (raise (Stop "halt" (get S "value")))))


;; ═══════════════════════════════════════════════════════════════
;; Trace / Seal  (v2: rich format with per-input hashes)
;; ═══════════════════════════════════════════════════════════════

(defn file-sig [p]
  (if (.exists (Path p))
      (.hexdigest (hashlib.sha256 (.read-bytes (Path p))))
      "0:absent"))

(defn recipe-spec [recipe]
  (when (is recipe None) (return "null"))
  (setv kind (get recipe "type"))
  (cond
    (= kind "action")
    (json.dumps {"type" "action"
                 "fn" (getattr (get recipe "fn") "__qualname__" "anon")}
                :sort-keys True)
    (= kind "oracle")
    (json.dumps {"type" "oracle"
                 "prompt" (.get recipe "prompt" "")
                 "tools" (sorted (.get recipe "tools" []))
                 "fuel" (.get recipe "fuel" 8)}
                :sort-keys True)
    (= kind "trial")
    (json.dumps {"type" "trial"
                 "branches" (lfor b (get recipe "branches") (recipe-spec b))}
                :sort-keys True)
    True "unknown"))

(defn compute-trace-parts [S inputs recipe]
  "Return the individual hash components (for staleness diagnosis)."
  (setv input-sigs (dict (lfor i (sorted inputs)
                           [i (file-sig (site-path S i))])))
  (setv rspec (recipe-spec recipe))
  {"inputs" input-sigs "recipe" rspec})

(defn composite-hash [parts]
  "Single hash over all trace parts."
  (.hexdigest (hashlib.sha256
    (.encode (json.dumps parts :sort-keys True)))))

(defn seal-file [S rule-name]
  (site-path S (+ ".traces/" rule-name ".seal")))

(defn read-seal [S rule-name]
  "Read the stored seal (rich JSON). Returns None if absent or corrupt."
  (setv sp (seal-file S rule-name))
  (when (not (exists? sp)) (return None))
  (try
    (json.loads (read-text sp))
    (except [e Exception] None)))

(defn all-outputs? [S outputs]
  (all (gfor o outputs (exists? (site-path S o)))))

(defn output-hashes [S outputs]
  "Compute hashes of the declared outputs."
  (lfor o outputs (file-sig (site-path S o))))

(defn freshness-check [S rule-name inputs outputs recipe]
  "Return None if sealed, or a reason string if stale."
  ;; missing outputs
  (for [o outputs]
    (when (not (exists? (site-path S o)))
      (return (+ o " missing"))))
  ;; no prior seal
  (setv prior (read-seal S rule-name))
  (when (is prior None)
    (return "no prior build"))
  ;; compare per-input hashes
  (setv current (compute-trace-parts S inputs recipe))
  (setv prior-inputs (.get prior "inputs" {}))
  (for [i (sorted inputs)]
    (setv cur-hash (get (get current "inputs") i))
    (setv old-hash (.get prior-inputs i ""))
    (when (!= cur-hash old-hash)
      (return (+ i " changed"))))
  ;; compare recipe
  (when (!= (get current "recipe") (.get prior "recipe" ""))
    (return "recipe changed"))
  ;; all match
  None)

(defn seal! [S rule-name inputs recipe]
  "Write the rich seal: per-input hashes + recipe spec."
  (setv parts (compute-trace-parts S inputs recipe))
  (write-text (seal-file S rule-name)
              (json.dumps parts :indent 2)))


;; ═══════════════════════════════════════════════════════════════
;; Node constructors
;; ═══════════════════════════════════════════════════════════════

(defn rule [name #* children #** kwargs]
  {"type" "rule" "name" name "children" (list children)
   "inputs" (.get kwargs "inputs" []) "outputs" (.get kwargs "outputs" [])
   "recipe" (.get kwargs "recipe" None)})

(defn action [f]
  {"type" "action" "fn" f})

(defn oracle [#* args #** kwargs]
  (setv name (when (and args (isinstance (get args 0) str))
               (get args 0)))
  {"type" "oracle" "name" name
   "prompt" (.get kwargs "prompt" "")
   "tools" (.get kwargs "tools" [])
   "fuel" (.get kwargs "fuel" 8)})

(defn trial [#* branches #** kwargs]
  {"type" "trial" "branches" (list branches)
   "verdict" (.get kwargs "verdict" None)})

(defn ->commit [value]
  {"type" "commit" "value" value})

(defn ->halt [reason]
  {"type" "halt" "reason" reason})


;; ═══════════════════════════════════════════════════════════════
;; Evaluator
;; ═══════════════════════════════════════════════════════════════

(defn eval-node [S node]
  (setv kind (get node "type"))
  (cond
    (= kind "rule")   (eval-rule S node)
    (= kind "commit") (do (setv (get S "status") "committed")
                          (setv (get S "value") (get node "value"))
                          (raise (Stop "commit" (get node "value"))))
    (= kind "halt")   (do (setv (get S "status") "halted")
                          (setv (get S "value") (get node "reason"))
                          (raise (Stop "halt" (get node "reason"))))
    True (raise (ValueError (+ "unknown node type: " kind)))))


(defn eval-rule [S node]
  (setv name    (get node "name"))
  (setv inputs  (get node "inputs"))
  (setv outputs (get node "outputs"))
  (setv recipe  (get node "recipe"))

  ;; 1. resolve prerequisites (with parent tracking for diamond annotations)
  (T.push-rule name)
  (for [child (get node "children")]
    (eval-node S child))
  (T.pop-rule)

  ;; 2. freshness check
  (setv reason (freshness-check S name inputs outputs recipe))
  (when (is reason None)
    ;; sealed — report with artifact hashes
    (.append (get S "trace") {"event" "sealed" "rule" name})
    (T.rule-sealed name
      :outputs outputs
      :output-hashes (output-hashes S outputs))
    (return))

  ;; 3. stale — fire
  (burn S name)
  (T.rule-start name :stale-reason reason)
  (try
    (eval-recipe S name recipe inputs outputs)
    (seal! S name inputs recipe)
    (.append (get S "trace") {"event" "fired" "rule" name "outputs" outputs})
    (T.rule-done name
      :outputs outputs
      :output-hashes (output-hashes S outputs))
    (except [e Stop] (raise))
    (except [e Exception]
      (T.rule-halted name (str e))
      (raise))))


(defn eval-recipe [S rule-name recipe inputs outputs]
  (when (is recipe None) (return))
  (setv kind (get recipe "type"))
  (cond
    (= kind "action") ((get recipe "fn") S)
    (= kind "oracle") (eval-oracle S rule-name recipe outputs)
    (= kind "trial")  (eval-trial S rule-name recipe outputs)
    True (raise (ValueError (+ "unknown recipe: " kind)))))


;; ── oracle ──────────────────────────────────────────────────

(defn default-oracle-backend [S rule-name recipe outputs]
  (for [o outputs]
    (write-text (site-path S o)
                (+ "# oracle output: " rule-name "\n"
                   "# prompt: " (.get recipe "prompt" "") "\n")))
  {"tokens_in" 840 "tokens_out" 320 "cost_usd" 0.0008})

(defn eval-oracle [S rule-name recipe outputs]
  (setv oname (or (.get recipe "name") "oracle"))
  (T.oracle-start rule-name oname (.get recipe "prompt"))
  (setv t0 (time.time))
  (setv backend (or (get S "oracle-backend") default-oracle-backend))
  (setv usage (backend S rule-name recipe outputs))
  (setv elapsed (- (time.time) t0))
  (setv u (or usage {}))
  (T.oracle-done rule-name oname
    :tokens-in  (.get u "tokens_in" 0)
    :tokens-out (.get u "tokens_out" 0)
    :cost-usd   (.get u "cost_usd" 0.0)
    :elapsed    elapsed))


;; ── trial ───────────────────────────────────────────────────

(defn default-verdict [results]
  (setv valid (lfor r results :if (not (in "error" r)) r))
  (when (not valid) (raise (ValueError "trial: all branches failed")))
  ;; return winner + scores if available
  (setv scores {})
  (for [r valid]
    (setv (get scores (get r "name"))
          (.get r "score" 1.0)))
  {"winner" (get valid 0) "scores" scores})

(defn eval-trial [S rule-name recipe outputs]
  (setv branches (get recipe "branches"))
  (setv verdict-fn (or (get recipe "verdict") default-verdict))
  (setv results [])
  (setv fuel-spent 0)

  (for [branch branches]
    (setv bname (or (.get branch "name") (+ "branch-" (str (len results)))))
    (setv tmp (tempfile.mkdtemp :prefix (+ "trial-" bname "-")))
    (setv t0 (time.time))
    (try
      (shutil.copytree (get S "site") tmp :dirs-exist-ok True)
      (setv BS (fresh-store tmp (get S "fuel")
                            :oracle_backend (get S "oracle-backend")))
      ;; fire branch
      (eval-recipe BS bname branch [] outputs)
      (setv branch-elapsed (- (time.time) t0))
      ;; collect outputs
      (setv out-data {})
      (for [o outputs]
        (setv op (site-path BS o))
        (when (exists? op)
          (setv (get out-data o) (read-text op))))
      (+= fuel-spent (- (get S "fuel") (get BS "fuel")))
      ;; collect oracle cost for this branch
      (setv branch-cost (sum (gfor e T._oracle-events
                               :if (= (get e 1) bname)
                               (get e 4))))
      (setv branch-toks-in (sum (gfor e T._oracle-events
                                  :if (= (get e 1) bname)
                                  (get e 2))))
      (setv branch-toks-out (sum (gfor e T._oracle-events
                                   :if (= (get e 1) bname)
                                   (get e 3))))
      (.append results {"name" bname "outputs" out-data
                        "elapsed" branch-elapsed
                        "tokens_in" branch-toks-in
                        "tokens_out" branch-toks-out
                        "cost_usd" branch-cost})
      (except [e Exception]
        (.append results {"name" bname "error" (str e) "outputs" {}}))
      (finally
        (shutil.rmtree tmp :ignore-errors True))))

  ;; charge fuel
  (setv (get S "fuel") (- (get S "fuel") fuel-spent))

  ;; verdict (supports both old and new protocol)
  (setv vresult (verdict-fn results))
  (setv [winner scores]
    (if (and (isinstance vresult dict) (in "winner" vresult))
        [(get vresult "winner") (.get vresult "scores")]
        [vresult None]))

  ;; report branches with scores
  (for [r results]
    (setv rname (get r "name"))
    (setv score (when scores (.get scores rname)))
    (T.trial-branch rule-name rname
      :score score
      :tokens-in (.get r "tokens_in" 0)
      :tokens-out (.get r "tokens_out" 0)
      :cost-usd (.get r "cost_usd" 0.0)
      :elapsed (.get r "elapsed" 0.0)))

  (setv wname (get winner "name"))
  (T.trial-verdict rule-name wname :scores scores)

  ;; copy winner outputs
  (for [o outputs]
    (when (in o (get winner "outputs"))
      (write-text (site-path S o) (get (get winner "outputs") o))))

  (.append (get S "trace")
           {"event" "trial" "rule" rule-name "winner" wname}))


;; ═══════════════════════════════════════════════════════════════
;; build
;; ═══════════════════════════════════════════════════════════════

(defn build [name fuel #* nodes #** kwargs]
  (setv site (or (.get kwargs "site" None)
                 (+ "/tmp/mccarthy-" name "-"
                    (cut (str (uuid.uuid4)) 0 8))))
  (setv S (fresh-store site fuel
                       :oracle_backend (.get kwargs "oracle_backend" None)))

  (.append (get S "trace")
           {"event" "build-start" "name" name "site" site "fuel" fuel})
  (T.build-start name fuel site
    (.get kwargs "oracle_model" None))

  (try
    (for [node nodes]
      (eval-node S node))
    (when (= (get S "status") "running")
      (setv (get S "status") "committed")
      (setv (get S "value") "ok")
      (.append (get S "trace") {"event" "auto-commit"}))
    (except [e Stop] None)
    (except [e Exception]
      (setv (get S "status") "halted")
      (setv (get S "value") (+ "error: " (str e)))
      (.append (get S "trace")
               {"event" "error" "message" (str e)})))

  ;; sealed artifact manifest
  (T.sealed-manifest)

  (.append (get S "trace")
           {"event" "build-end" "status" (get S "status")})
  (T.build-end (get S "status") (get S "fuel") fuel)
  S)
