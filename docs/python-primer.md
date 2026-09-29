# Python primer for Tetralux-1

Every Python concept this project uses, explained once, with real examples from
this codebase. The source files assume you have read this: they explain *what a
particular function does*, not *what the word `def` means*.

Read it top to bottom once. After that, use it as a lookup table.

---

## 1. What a program actually is

A Python file is a list of instructions. Python reads it top to bottom, one line
at a time, and does what each line says.

```python
x = 5          # store the number 5 under the name "x"
y = x * 2      # look up x, multiply by 2, store the result as "y"
print(y)       # show y on the screen  ->  10
```

`=` does **not** mean "equals" the way it does in maths. It means **"put the
thing on the right into the name on the left."** So `x = x + 1` is not a
contradiction; it means "take x, add one, put it back into x."

A name like `x` or `total` is called a **variable**.

---

## 2. `print()`

`print()` writes text to the terminal. It is for a human watching a program run.

```python
print("calibration complete")
```

**It is not how a program returns an answer.** `print` shows something and then
throws it away. If another part of the program needs the value, you must
`return` it (section 5).

In this project `print` appears only 12 times, all in the three command-line
tools a person runs by hand:

- `src/tetralux/groundstation.py`
- `src/tetralux/calibration_tool.py`
- `src/tetralux/store/session.py`

Everything else is a library: it computes values and hands them back, and the
dashboard decides what to display. That separation is deliberate. A function
that prints can only ever talk to a terminal; a function that returns can feed a
web page, a file, a test, or another calculation.

### f-strings

A string with an `f` in front can embed values inside `{}`:

```python
total = 4410
print(f"total signal {total} counts")     # total signal 4410 counts
print(f"total signal {total:.2e} counts") # total signal 4.41e+03 counts
```

The part after `:` is a **format spec**. `.2e` means "scientific notation, 2
decimal places". `.3f` means "3 decimal places". `.0f` means "no decimals".

---

## 3. `def`: defining a function

A **function** is a named, reusable block of code.

```python
def add(a, b):
    return a + b
```

Two separate moments matter here, and mixing them up is the single most common
beginner confusion:

1. **Definition.** When Python reads the `def` line, it does *not* run the code
   inside. It only memorises "there is a thing called `add`".
2. **Call.** When some other line says `add(2, 3)`, *then* the body runs.

```python
result = add(2, 3)   # now the body runs, result becomes 5
```

The indented lines below `def` are the **body**. Indentation is how Python knows
what belongs to the function; it is not decoration. Four spaces, consistently.

---

## 4. Parameters and arguments

In `def add(a, b):`, the names `a` and `b` are **parameters**: placeholders.

In `add(2, 3)`, the values `2` and `3` are **arguments**: the real values that
get poured into those placeholders for this one call.

So during `add(2, 3)`, inside the function `a` is 2 and `b` is 3. On the next
call `add(10, 1)`, `a` is 10. The parameter names exist only inside the
function.

### Keyword arguments

You can pass by name instead of by position, which is clearer with several:

```python
simulate_faces(sun_vector, intensity=1000.0)
```

### Default values

A parameter can have a fallback, used when the caller does not supply one:

```python
def corrected_reading(V_i, D_i=0.0, G_i=1.0):
    ...
```

`corrected_reading(500)` behaves as `corrected_reading(500, 0.0, 1.0)`.

**A trap this project actually hit.** A default is computed *every time*, even
when it is not used:

```python
prompts.get(step, f"...{step.split(':')[1]}...")
```

The `.get()` returns the found value, but Python must build the default first,
before it can hand it to `.get()`. When `step` had no `:` in it, that crashed
even though the answer was found. The fix was an `if`/`elif` chain, in
`calibration_tool.py`.

---

## 5. `return`

`return` does two things at once:

1. Hands a value back to whoever called the function.
2. **Ends the function immediately.** Code written after a `return` never runs.

```python
def face_weight(R_i, all_R):
    total = sum(all_R)
    return R_i / total
    print("never happens")   # unreachable
```

A function with no `return` hands back `None` (section 8).

Multiple returns are fine and often clearer than nesting:

```python
def _resolve(param, face, default):
    if isinstance(param, Mapping):
        return float(param.get(face, default))   # exits here if a dict
    return float(param)                          # otherwise exits here
```

You can return several values at once as a **tuple**:

```python
def sun_angles(v):
    return azimuth, elevation

az, el = sun_angles(vector)   # unpacked into two names
```

---

## 6. Type hints

```python
def face_weight(R_i: float, all_R: Sequence[float]) -> float:
```

- `R_i: float` means "R_i is expected to be a decimal number".
- `-> float` means "this function hands back a decimal number".

**Python does not enforce these.** Passing a string will not raise an error at
the hint; it will just fail later somewhere more confusing. Hints exist for
humans reading the code and for tools that check it.

| Hint | Meaning |
|---|---|
| `int` | whole number: `7` |
| `float` | decimal: `7.5` |
| `str` | text: `"+x"` |
| `bool` | `True` or `False` |
| `list[float]` | a list of decimals |
| `dict[str, float]` | keys are text, values are decimals |
| `Optional[int]` | an `int` **or** `None` |
| `np.ndarray` | a NumPy array (section 13) |

### `from __future__ import annotations`

At the top of most files here. It makes Python store type hints as plain text
instead of evaluating them, which lets this code use modern syntax like
`list[str]` while still running on Python 3.9.

`__future__` is not a file in this project. It is a special module built into
Python itself; importing from it flips a switch that changes how the rest of
*that one file* is interpreted.

**It is deliberately absent from `ingest/http_server.py`**, and there is a
comment there saying why. FastAPI *reads* the hints at runtime to decide what
each parameter is. With the future import on, it saw the text `"Request"`
instead of the actual class, could not resolve it, assumed it was a URL query
parameter, and rejected every upload with a 422 error. That bug cost real
debugging time; the comment exists so nobody "tidies" the import back in.

---

## 7. Data structures

### list

An ordered sequence. Square brackets. Positions count from **0**.

```python
FACE_NAMES = ["+x", "-x", "+y", "-y", "+z", "-z"]
FACE_NAMES[0]    # "+x"
FACE_NAMES[5]    # "-z"
len(FACE_NAMES)  # 6
```

### dict

A lookup table of key to value. Curly braces.

```python
weights = {"+x": 0.5, "-x": 0.0}
weights["+x"]           # 0.5
weights.get("+q", 0.0)  # 0.0  (no crash: .get returns a default if missing)
```

Compare `weights["+q"]`, which raises `KeyError` and stops the program.

Nearly every per-face quantity in this project is a dict keyed by face name.
That is why `FACE_NAMES` exists in `constants.py`: it fixes one canonical order,
so a list of six numbers from the hardware and a dict of six named values can
always be converted back and forth reliably.

### tuple

Like a list, but cannot be changed after creation. Round brackets: `(az, el)`.

---

## 8. `None`

`None` is Python's word for "no value here". It is not zero, and not empty text.

This project uses it precisely: `sun_vector` is `None` when the frame was too
dark to resolve a direction. That is different from a zero vector, which would
falsely claim a measurement was made.

Test with `is` / `is not`, never `==`:

```python
if rec.sun_vector is not None:
    ...
```

---

## 9. `if` / `elif` / `else`

```python
if abs(total) < MIN_EPSILON:
    raise LowSignalError(...)
elif total < 0:
    ...
else:
    ...
```

Python checks each condition in order and runs the body of the **first** one
that is true, then skips the rest.

Comparisons: `==` equal, `!=` not equal, `<`, `>`, `<=`, `>=`.
Combine with `and`, `or`, `not`.

Note `==` (a question: "are these equal?") versus `=` (a command: "store this").

---

## 10. `for` loops

```python
for face in FACE_NAMES:
    print(face)          # runs six times, face is a different name each pass
```

`enumerate()` gives you the position as well, used throughout this codebase to
pair the hardware's list of six numbers with their face names:

```python
{f: self.photodiodes[i] for i, f in enumerate(FACE_NAMES)}
```

`zip()` walks two sequences side by side:

```python
for w, n in zip(weights, face_normals):
    d = d + w * n
```

### Comprehensions

A compact way to build a list or dict from a loop. These two are identical:

```python
corrected = []
for r in readings:
    corrected.append(r * 2)
```
```python
corrected = [r * 2 for r in readings]
```

The dict version uses `{key: value for ...}`. Read them right to left: "for each
r in readings, give me r * 2."

---

## 11. Errors and `raise`

When a function is asked to do something impossible, it has two options: return
a meaningless number, or refuse loudly. Refusing loudly is almost always right,
because a meaningless number silently poisons every calculation downstream.

```python
raise LowSignalError("total signal below MIN_EPSILON")
```

`raise` aborts the function immediately and reports the problem to the caller.

### Defining your own error type

```python
class LowSignalError(Exception):
    """Raised when total signal is below MIN_EPSILON."""
```

A custom type lets callers catch *this specific* problem while letting genuine
bugs through.

### Catching one

```python
try:
    s_hat = estimate_sun_vector(readings)
except LowSignalError:
    s_hat = None          # too dark: report honestly, keep running
```

`try` runs the risky code; `except` runs only if that specific error occurred.
The pipeline uses exactly this so one dark frame does not kill the ground
station.

Catching bare `except:` with no type is a bad habit: it swallows typos and
interrupts along with the error you meant to handle.

---

## 12. Classes and objects

A **class** is a template that bundles data with the functions that work on it.
An **object** (or instance) is one thing built from that template.

```python
class LocalLog:
    def __init__(self, session_id, base_dir):
        self.session_id = session_id     # stored on THIS object
        self.base_dir = base_dir

    def append(self, record):
        ...
```

- `__init__` is the **constructor**: it runs once, automatically, when you write
  `LocalLog("S1", "data/")`. Its job is to set up the object's starting data.
- `self` is the object itself. Every method takes it as the first parameter, and
  **you never pass it manually**: `log.append(rec)` calls `append(log, rec)`
  behind the scenes. Anything stored as `self.something` survives between calls;
  a plain local variable does not.
- A function that lives inside a class is called a **method**.

Names with double underscores like `__init__` are hooks Python calls for you at
defined moments. You write them; Python decides when they run.

### `@dataclass`

A **decorator**: a line starting with `@` above a `def` or `class` that modifies
it. `@dataclass` writes the boring `__init__` for you.

```python
@dataclass
class SensorFrame:
    seq: int
    timestamp_ms: int
    source: str = "real"
```

That is enough to create `SensorFrame(seq=1, timestamp_ms=500)`.

`field(default_factory=_utcnow)` handles a subtlety: a plain default like
`received_at = _utcnow()` would be computed **once**, when the class is defined,
so every frame ever created would share one stale timestamp. `default_factory`
says "call this function fresh for each new object".

### Leading underscore

`_utcnow`, `_resolve`, `_flush_queue`. A single leading underscore is a
convention meaning **"internal, not part of this file's public interface"**.
Python does not enforce it. It tells a reader: safe to change, nothing outside
should be calling it.

---

## 13. Imports, modules, packages

Every `.py` file is a **module**. `import` lets one file use another's code.

```python
import numpy as np                                # whole module, nicknamed np
from tetralux.constants import FACE_NAMES         # one specific name
```

A folder of modules is a **package**. `__init__.py` marks a folder as one. Most
of them here are nearly empty, and a few **re-export** the useful names so
callers can write `from tetralux.estimation import sun_vector` instead of the
longer `from tetralux.estimation.estimator import sun_vector`.

`__main__.py` is what runs when you type `python -m tetralux.dashboard`.

### NumPy

`numpy` is the numerical library. Its **array** holds many numbers and does maths
on all of them at once:

```python
a = np.array([1.0, 0.0, 0.0])
b = np.array([0.0, 1.0, 0.0])
a + b               # array([1., 1., 0.])   element by element
a * 2               # array([2., 0., 0.])
np.linalg.norm(a)   # 1.0, the length of the vector
```

The whole sun-vector calculation is 3-element arrays representing directions in
space, which is why this project uses NumPy rather than plain lists.

---

## 14. `async def` and `await`

Normal Python does one thing at a time. If a line takes two seconds, everything
waits two seconds.

A web server cannot work that way: while waiting for one satellite packet to
arrive over the network, it must stay free to accept the next. `async def`
defines a function that can **pause at an `await` and let other work run** while
it waits.

```python
async def ingest(request: Request):
    payload = await request.body()   # pause here; server handles others
    ...
```

`await` means "this will take a while; go do something else and come back when
it is ready". You can only use `await` inside an `async def`.

**This project has exactly two `async def` functions**, both in
`src/tetralux/ingest/http_server.py`, because that is the only place the code
runs as a web server (FastAPI). Everything else is ordinary sequential Python.
Concurrency elsewhere is handled with **threads** instead, in
`ingest/monitor.py` and `dashboard/state.py`.

---

## 15. Docstrings versus comments

```python
def face_weight(R_i, all_R):
    """Formula 2 - face weight: w_i = R_i / sum(all_R)."""   # docstring
    # this is a comment
```

- A **comment** starts with `#`. Python ignores it entirely.
- A **docstring** is a string on the first line inside a `def` or `class`.
  Python keeps it, and `help(face_weight)` will show it.

Both are for humans. Docstrings describe *what and why* for someone using the
function; comments explain *how* for someone reading the implementation.

---

## 16. How to actually explore this yourself

```bash
python
```

opens an interactive prompt where you can poke at anything:

```python
>>> from tetralux.sim.simulator import simulate_faces
>>> import numpy as np
>>> simulate_faces(np.array([1.0, 0.0, 0.0]), intensity=1000.0)
```

Change a number, run it again, see what moves. That loop teaches faster than
reading does.

To check you have not broken anything:

```bash
pytest
```
