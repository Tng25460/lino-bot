#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-state/live.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ introuvable: $ENV_FILE" >&2
  exit 1
fi

echo "🔎 scan doublons dans: $ENV_FILE"
# liste les noms de variables (export VAR=... ou VAR=...)
vars=$(rg -n '^\s*(export\s+)?[A-Za-z_][A-Za-z0-9_]*=' "$ENV_FILE" \
  | sed -E 's/^\s*(export\s+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/' \
  | sort)

# affiche celles qui apparaissent >1 fois
dups=$(printf "%s\n" "$vars" | uniq -c | awk '$1>1{print}')
if [[ -z "${dups}" ]]; then
  echo "✅ aucun doublon détecté"
  exit 0
fi

echo "⚠️ doublons détectés (count var):"
echo "$dups" | sed 's/^/  /'

echo
echo "➡️ occurrences exactes:"
# pour chaque var dupliquée, affiche les lignes
printf "%s\n" "$dups" | awk '{print $2}' | while read -r v; do
  echo "----- $v -----"
  rg -n "^\s*(export\s+)?${v}=" "$ENV_FILE" || true
done

echo
echo "💡 Fix rapide (manuel): supprime les doublons avec sed -i '/${VAR}=/d' puis ré-ajoute une seule ligne export VAR=..."
