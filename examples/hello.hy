#!/usr/bin/env hy
"A tiny Husks build expressed in Hy's s-expression syntax.

Defines two rules -- an action that writes a greeting file and a
commit rule that depends on it -- then runs the build via the
Python API and prints the result.

Usage:
    hy examples/hello.hy

Requires: pip install husks[hy]
"

(import husks.build [build rule action])

;; --- action recipe: write a greeting into the site ---
(defn write-greeting [store]
  (let [path (+ (get store "site") "/hello.txt")]
    (with [f (open path "w")]
      (.write f "Hello from Husks + Hy!\n"))))

;; --- build graph ---
(setv greet-rule
  (rule "greet"
        :outputs ["hello.txt"]
        :recipe (action write-greeting)))

(setv finish-rule
  (rule "finish"
        greet-rule
        :inputs ["hello.txt"]
        :outputs [".done"]))

;; --- run ---
(defn main []
  (let [store (build "hello-hy" 10 finish-rule)]
    (print "build status:" (get store "status"))
    (print "site:" (get store "site"))))

(when (= __name__ "__main__")
  (main))
