#!/bin/bash
# Export module files for migration
cd /Users/nick/guideai
OUTPUT="module_migration_export.txt"
> "$OUTPUT"

FILES=(
  "guideai/research/__init__.py"
  "guideai/research/codebase_analyzer.py"
  "guideai/research/prompts.py"
  "guideai/research/report.py"
  "guideai/research/ingesters/__init__.py"
  "guideai/research/ingesters/base.py"
  "guideai/research/ingesters/markdown_ingester.py"
  "guideai/research/ingesters/pdf_ingester.py"
  "guideai/research/ingesters/url_ingester.py"
  "guideai/crypto/__init__.py"
  "guideai/crypto/signing.py"
  "guideai/billing/__init__.py"
  "guideai/billing/service.py"
  "guideai/billing/api.py"
  "guideai/billing/webhook_routes.py"
  "guideai/analytics/__init__.py"
  "guideai/analytics/telemetry_kpi_projector.py"
  "guideai/analytics/warehouse.py"
  "guideai/research_contracts.py"
  "guideai/research_service.py"
)

for f in "${FILES[@]}"; do
  echo "=== FILE: $f ===" >> "$OUTPUT"
  cat "$f" >> "$OUTPUT"
  echo "" >> "$OUTPUT"
done

echo "Exported ${#FILES[@]} files to $OUTPUT"
wc -l "$OUTPUT"
