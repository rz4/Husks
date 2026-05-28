"Hy macros for Husks design files.

    (require husks.macros [defaction deforacle])
"

(defmacro defaction [name params #* body]
  "Define an action recipe factory.

  The Store (S) is implicit -- do not include it in the param list.
  It is available as ``S`` in the body::

      (defaction stage-files [#* files]
        (for [f files]
          (shutil.copy f (site_path S f))))

      ;; returns an action recipe dict:
      (stage-files \"a.txt\" \"b.txt\")
  "
  (setv impl (hy.models.Symbol (+ "_" (str name) "-impl")))
  (setv impl-params (+ [(hy.models.Symbol "S")] (list params)))
  `(do
     (defn ~impl ~impl-params ~@body)
     (defn ~name [#* _args]
       (action ~impl #* _args))))

(defmacro deforacle [name #* defaults]
  "Define a named oracle recipe factory.

  The oracle name is set from the macro name.  Keyword args become
  the oracle defaults::

      (deforacle generate-reader
        :prompt \"Read the spec and implement a reader.\"
        :tools [\"read-file\" \"write-file\"]
        :fuel 8)

      ;; returns an oracle recipe dict:
      (generate-reader)
  "
  (setv name-str (str name))
  `(defn ~name []
     (oracle ~name-str ~@defaults)))
