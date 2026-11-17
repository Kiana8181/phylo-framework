#!/bin/bash
set -e
Rscript -e 'cat(system.file(package="BrepPhylo"), "\n")'
pkg=$(Rscript -e 'cat(system.file(package="BrepPhylo"))')
echo "PKG=$pkg"
grep -R -n -E "pdflatex|latexmk|knit|xtable|tinytex" "$pkg" --include='*.R' --include='*.Rd' | head -n 40
