"Hy macros for Husks design files.

    (require husks.macros [defaction])
"

(defmacro defaction [name params #* body]
  "Define an action recipe factory.

  Generates an implementation function with the given params (first
  param is the Store) and a public function that returns an action
  recipe dict when called with the remaining args::

      (defaction stage-files [S #* files]
        (for [f files]
          (shutil.copy f (site_path S f))))

      ;; returns an action recipe dict:
      (stage-files \"a.txt\" \"b.txt\")
  "
  (setv impl (hy.models.Symbol (+ "_" (str name) "-impl")))
  `(do
     (defn ~impl ~params ~@body)
     (defn ~name [#* _args]
       (action ~impl #* _args))))
