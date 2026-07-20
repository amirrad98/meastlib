#!/usr/bin/env bash
# Download the solr-ocrhighlighting plugin jar (Solr 9 build) into solr/lib/.
# Releases: https://github.com/dbmdz/solr-ocrhighlighting/releases
set -euo pipefail

VERSION="${1:-0.9.5}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/solr/lib"
mkdir -p "$DIR"

URL="https://github.com/dbmdz/solr-ocrhighlighting/releases/download/${VERSION}/solr-ocrhighlighting-${VERSION}.jar"
echo "Fetching $URL"
curl -fL -o "$DIR/solr-ocrhighlighting-${VERSION}.jar" "$URL"
echo "Done -> $DIR"
echo "If the filename for the Solr 9 build differs (check the release page), pass it explicitly."
