;; kernel.hy — agentic kernel
;; C = context, M = model inference

;-
(import husks.llm :as llm)
(import husks.trace :as T)
(import husks.tools :as tools)
(import json)

;--
(defn rebind [C event]
  (| C {"trace" (+ (.get C "trace" []) [event])}))

;--
(defn allowed? [C tool]
  (in tool (.get C "tools" [])))

;--
(defn parse-response [r]
  "Extract the first actionable block from a litellm response (OpenAI shape)."
  (setv msg (get (get r.choices 0) "message"))
  (setv tc (getattr msg "tool_calls" None))
  (cond
    ;; tool call present
    (and tc (> (len tc) 0))
    (let [call (get tc 0)
          fn-obj call.function
          name (.replace fn-obj.name "_" "-")
          args (try (json.loads (or fn-obj.arguments "{}"))
                    (except [e Exception] {}))]
      {"type" "act" "tool" name "args" args
       "tool_call_id" call.id})
    ;; finished
    (= (get (get r.choices 0) "finish_reason") "stop")
    {"type" "stop" "value" (or msg.content "")}
    ;; otherwise treat as say
    True
    {"type" "say" "text" (or msg.content "")}))

;--
(defn _build-messages [C]
  "Build OpenAI messages list from initial prompt + trace of tool calls."
  (setv msgs [{"role" "user" "content" (.get C "prompt" "Run the task.")}])
  (for [event (.get C "trace" [])]
    (let [form (.get event "form" {})
          kind (.get form "type" "")]
      (when (= kind "act")
        (let [tid (.get form "tool_call_id" "t0")
              tool-name (.get event "tool" "unknown")
              tool-args (.get form "args" {})
              out (.get event "out" "")
              out-str (if (isinstance out str) out (json.dumps out :default str))
              fn-name (.replace tool-name "-" "_")]
          ;; assistant message with tool_calls array
          (.append msgs {"role" "assistant"
                         "content" None
                         "tool_calls" [{"id" tid
                                        "type" "function"
                                        "function" {"name" fn-name
                                                    "arguments" (json.dumps tool-args)}}]})
          ;; tool result message
          (.append msgs {"role" "tool"
                         "tool_call_id" tid
                         "content" (cut out-str 0 8000)})))))
  msgs)

;--
(defn invoke-llm [C]
  (let [msgs (_build-messages C)
        tool-schemas (.get C "tool-defs" [])
        kwargs {"model" (.get C "model" "anthropic/claude-haiku-4-5-20251001")
                "max_tokens" (.get C "max-tokens" 4096)
                "rule" (.get C "rule" None)}]
    (when (.get C "system" None)
      (setv (get kwargs "system") (get C "system")))
    (when tool-schemas
      (setv (get kwargs "tools") tool-schemas))
    (setv r (llm.call_messages msgs #** kwargs))
    (parse-response r)))

;--
(defn step [M C tools-map fuel]
  (try
    (let [form (M C)
          kind (.get form "type")]
      (cond
        (<= fuel 0)
        {"type" "halt" "C" C "fuel_steps" 0}

        (= kind "say")
        {"type" "say" "text" (.get form "text") "C" C "fuel_steps" 0}

        (= kind "stop")
        {"type" "stop" "value" (.get form "value" C) "C" C "fuel_steps" 0}

        (= kind "act")
        (let [name (.get form "tool")
              args (.get form "args" {})]
          (if (not (allowed? C name))
              {"type" "error" "error" (+ name " not in scope") "C" C "fuel_steps" 0}
              (do
                (T.tool-call (.get C "rule" "agent") name args)
                (let [out (tools.dispatch name args)
                      C2  (rebind C {"form" form "tool" name "out" out})]
                  (T.tool-result name out)
                  (setv result (step M C2 tools-map (- fuel 1)))
                  (setv (get result "fuel_steps")
                        (+ 1 (.get result "fuel_steps" 0)))
                  result))))

        True
        {"type" "error" "error" (+ "bad form: " (str form)) "C" C "fuel_steps" 0}))
    (except [KeyboardInterrupt]
      {"type" "kill" "C" C "fuel_steps" 0})))

;--
(defn agent [C * [fuel 8] [M invoke-llm]]
  (let [tool-names (.get C "tools" [])
        tool-defs (tools.schemas tool-names)
        C0 (| {"trace" [] "tool-defs" tool-defs} C)]
    (step M C0 None fuel)))


;; ═══════════════════════════════════════════════════════════════
;; Live oracle — adapts agent() to the build's oracle backend signature
;; ═══════════════════════════════════════════════════════════════

(setv _oracle-model "anthropic/claude-haiku-4-5-20251001")

(defn set-oracle-model [model]
  (global _oracle-model)
  (setv _oracle-model model))

(defn live-oracle [S rule-name recipe outputs]
  "Run the kernel as a build oracle. Returns usage dict."
  (setv site (get S "site"))
  (setv prompt (.get recipe "prompt" ""))
  (setv tool-names (.get recipe "tools" ["read-file" "write-file" "list-dir" "tree"]))
  (setv fuel (.get recipe "fuel" 8))

  ;; enforce site containment at the tool layer
  (tools.set-site-root site)

  ;; tell the oracle where it is and what it must produce
  (setv system
    (+ "You are an oracle inside a build system.\n"
       "Site directory: " site "\n"
       "All file paths must be absolute, rooted at the site.\n"
       "You must produce these outputs:\n"
       (.join "\n" (lfor o outputs (+ "  - " site "/" o)))
       "\n\nUse the available tools to read inputs and write outputs. "
       "When finished, stop."))

  ;; snapshot usage before
  (setv before (llm.get-usage))
  (setv ti0 (get before "input_tokens"))
  (setv to0 (get before "output_tokens"))
  (setv c0  (get before "cost_usd"))

  ;; run the kernel
  (setv result
    (try
      (agent {"prompt" prompt
              "tools"  tool-names
              "system" system
              "model"  _oracle-model
              "rule"   rule-name}
             :fuel fuel)
      (finally
        (tools.set-site-root None))))

  ;; compute delta
  (setv after (llm.get-usage))
  {"tokens_in"   (- (get after "input_tokens") ti0)
   "tokens_out"  (- (get after "output_tokens") to0)
   "cost_usd"    (- (get after "cost_usd") c0)
   "fuel_steps"  (.get result "fuel_steps" 0)})
