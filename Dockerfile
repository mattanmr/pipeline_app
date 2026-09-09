# Dockerfile — Phase 4 (centralized/CLI deployment)
#
# No pip dependencies (stdlib only), so this is just Python + tkinter.
# Note: the GUI (gui/app.py) needs a display, which a plain container
# doesn't have — this image is meant for running the CLI (main.py) in
# a pipeline/automation context, not for launching the desktop GUI.
# python:3.11-slim does NOT ship tkinter by default, hence the apt step.

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends python3-tk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
