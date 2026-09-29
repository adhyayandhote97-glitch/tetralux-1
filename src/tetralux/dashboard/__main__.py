"""Entry point: ``python -m tetralux.dashboard`` launches the demo dashboard.

WHAT THIS FILE CONTRIBUTES
--------------------------
Six lines that make one command work:

    python -m tetralux.dashboard

WHAT __main__.py IS. When you run `python -m some.package`, Python looks inside
that package for a file called __main__.py and runs it. So this file is what
turns an importable package into something you can execute from a terminal.

The name is not a coincidence: it is the same `__main__` as in the
`if __name__ == "__main__":` guard below. Python sets a module's `__name__` to
"__main__" when it is the file being run directly, and to the module's own name
when it is merely imported.

WHY IT DOES ALMOST NOTHING. All the real work is in app.py's main(). Keeping the
entry point separate and trivial means app.py stays a normal importable module
that tests can pull apart, while the command-line convenience lives here. The
same split appears in groundstation.py and calibration_tool.py, which use the
`if __name__` guard at the bottom of the module instead.

The dashboard starts in Virtual mode, so it is fully usable with no hardware
attached. It serves at http://127.0.0.1:8050.

New to Python? Read docs/python-primer.md first.
"""

from tetralux.dashboard.app import main

# The guard is technically redundant here, since a __main__.py is only ever run
# directly, but it is the universal Python convention and costs nothing. It also
# means the file behaves correctly if someone ever imports it by accident.
if __name__ == "__main__":
    # No brackets on the import above, brackets here: the function was imported
    # as a value, and this is where it is actually called. It blocks until the
    # server stops, normally with Ctrl-C.
    main()
