#!/bin/bash
pkg=/usr/lib64/R/library/BrepPhylo
find "$pkg" -type f | head -n 80
echo "---- grep ----"
grep -R -n -i -E "latex|pdf|tex" "$pkg" | head -n 60
