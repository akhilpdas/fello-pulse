#!/usr/bin/env bash
# Builds docs/Pulse_Test_Walkthrough.docx (and .pdf) from the markdown + screenshots in this folder.
#   bash docs/walkthrough/build.sh        (needs pandoc and LibreOffice; screenshots come from capture.mjs)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
# pandoc's Word writer ignores LaTeX \newpage, so turn it into a real Word page break
python3 - "$TMP/src.md" <<'PY'
import sys, pathlib
s = pathlib.Path("Pulse_Test_Walkthrough.md").read_text()
brk = '\n```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n'
pathlib.Path(sys.argv[1]).write_text(s.replace("\\newpage", brk))
PY
cp -R img "$TMP/img"
(cd "$TMP" && pandoc src.md -o out.docx --from markdown+pipe_tables+fenced_code_blocks)
cp "$TMP/out.docx" ../Pulse_Test_Walkthrough.docx
soffice --headless --convert-to pdf --outdir ../ ../Pulse_Test_Walkthrough.docx >/dev/null 2>&1 || echo "PDF conversion skipped (LibreOffice not found)"
ls -lh ../Pulse_Test_Walkthrough.*
