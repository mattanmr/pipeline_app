# Pipeline Management Application

Schema-driven folder creation, the version cascade, AI-generation
metadata tracking, a client-material ingest step, and a Tkinter
desktop GUI on top of all of it. **Zero external dependencies** —
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

## Quick start — CLI

```bash
# 1. Create a project (creates References/Client_Materials/Docs/Sequences/Export)
python main.py init-project "Demo_Show" --root ./workspace \
    --production-folder "//NAS/Production/Demo_Show"

# 2. Create a sequence and a shot
python main.py create-sequence "Demo_Show" SEQ010 --root ./workspace
python main.py create-shot "Demo_Show" SEQ010 SHOT010 --root ./workspace

# 3. Publish a version into a category (file or folder both work —
#    folders are for EXR sequences etc.)
python main.py publish "Demo_Show" SEQ010 SHOT010 Animation \
    ./scratch/anim_take.abc --root ./workspace

# 4. Publish an AI-generated asset with model/prompt metadata
python main.py publish "Demo_Show" SEQ010 SHOT010 AI_Generated/Images \
    ./scratch/frame_0001.png --root ./workspace \
    --model "Midjourney v6" --prompt "wide establishing shot, dusk"

# AI video citing which image version it was generated from
# (source can point at ANY category, not just AI_Generated/Images)
python main.py publish "Demo_Show" SEQ010 SHOT010 AI_Generated/Video \
    ./scratch/gen_video.mp4 --root ./workspace \
    --model "Veo 3" --prompt "animate with a slow camera push" \
    --ai-source "AI_Generated/Images:v001"

# 5. Record a shot cut — an explicit, artist-driven composition step.
#    Publishing a category does NOT automatically create a new cut.
python main.py record-shot-cut "Demo_Show" SEQ010 SHOT010 --root ./workspace \
    --source "Animation:v001" --source "AI_Generated/Video:v001"

# 6. Inspect the resulting tree
python main.py tree "Demo_Show" --root ./workspace
```

The client-material ingest step (publish into `Client_Materials` +
`record_client_material_usage()`) is currently GUI-only, on the
**Ingest Client Material** tab.

## What's implemented

- `config/pipeline_schema.json` — the folder structure as data, matching
  the design: Project > Sequences > Shots, project-level categories
  (References/Client_Materials/Docs), shot-level categories
  (Footage/Animation/Renders/Effects/Sound), AI_Generated/{Images,Video},
  Export, and the versions/master + cut_versions/cut_master patterns.
- `config/settings.json` — local machine config: local scratch workspace
  path, shared storage path, schema path.
- `core/manager.py` — builds the physical tree from the schema and
  initializes every tracking JSON file.
- `core/versioning.py` — the version cascade:
  - `publish()` — copies a file/folder into `versions/vXXX`, overwrites
    `master/`, records the new version (with AI model/prompt/source
    metadata where relevant).
  - `record_cut()` — the explicit composition step reused at shot,
    sequence, and project (Export) level: "this cut is made from these
    specific source versions."
  - `record_client_material_usage()` — notes that a shot drew on a
    specific `Client_Materials` version.
- `core/io_handler.py` — atomic, crash-safe copying for heavy media
  (stages into a `.partial` path, then replaces).
- `utils/naming.py`, `utils/metadata.py` — filename sanitization and
  JSON/version-record helpers.
- `main.py` — CLI covering every core operation, plus a `gui` subcommand.
- `gui/` — the Tkinter desktop app:
  - `components.py` — reusable widgets (labeled entries, file/folder
    pickers, the AI-metadata form, a status bar).
  - `views.py` — `AppContext` (shared workspace/project/sequence/shot
    selection + disk-scanning helpers) and one panel per screen.
  - `app.py` — loads `config/settings.json` + the schema, builds the
    tabbed window.

## Not built yet

- **Docker web deployment** — `Dockerfile` runs the CLI in a container
  (with `python3-tk` installed via apt, since `python:3.11-slim` doesn't
  ship it); there's no FastAPI/web layer, and the GUI isn't meant to run
  inside the container without X11 forwarding.
- **Standalone executable packaging** (PyInstaller or similar) for
  distributing the GUI to artists without a Python install.

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
