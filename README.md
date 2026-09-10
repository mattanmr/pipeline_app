# Pipeline Management Application

Schema-driven folder creation, the version cascade, AI-generation
metadata tracking, a client-material ingest step, and a Tkinter
desktop GUI on top of all of it. 
everything runs on the Python 3.10+ standard library (`json`, `os`,
`shutil`, `pathlib`, `argparse`, `tkinter`, `datetime`).

## Setup

Nothing to install for the app itself:

```bash
python main.py --help
```

(`tkinter` ships with most Python installs; on some Linux distros it's
a separate OS package — see *Troubleshooting* below if `python main.py gui`
complains it's missing.)

## Quick start — GUI

```bash
python main.py gui
```

Opens a tabbed window: **Projects** (pick a workspace root, create/select
a project) → **Sequences & Shots** (create/select) → **Publish** (choose
a category, browse a source file/folder, fill in AI model/prompt/source
fields when publishing into AI_Generated) → **Record Cut** (multi-select
published category versions to compose an explicit shot cut) →
**Ingest Client Material** (publish a client file into Client_Materials,
then optionally record that the currently selected shot used it) →
**Tree View** (read-only folder tree of the selected project).


## Design notes worth knowing before extending this

- `record_cut()` is deliberately **not automatic**. A new Animation
  publish doesn't create a new shot cut by itself, the same way a new
  AI-generated video isn't automatically part of an edit — composing
  a cut is a distinct, explicit step, reused unchanged at the
  sequence and Export level since they share the same versions/master
  + composition-record shape.
- `AI_Generated/Video` sources aren't restricted to
  `AI_Generated/Images` — a source can point at any category/version
  (Footage, Renders, ...), per the earlier design discussion. In the
  GUI this is a comma-separated `Category:version` field; in the CLI
  it's repeatable `--ai-source` flags.
- Every write to a tracking JSON is atomic (temp file + replace) and
  every heavy copy goes through a `.partial` staging path — a crash
  mid-publish should never leave a corrupt version or tracking file.
- The GUI holds no pipeline logic of its own — every button calls
  straight into `core/manager.py` / `core/versioning.py`, the same
  functions the CLI uses. `AppContext` in `gui/views.py` is the only
  GUI-side "smarts," and it's just disk scanning + selection state.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'tkinter'`** — on Debian/Ubuntu,
  install the OS package: `sudo apt-get install python3-tk`. On macOS/
  Windows, the standard python.org installer includes it already.
