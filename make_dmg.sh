#!/bin/bash
# Pulse Edit — build DMG with visual drag-to-Applications
# Run AFTER notarize.sh has produced dist/PulseEdit.app (signed + stapled).
#
# Output: dist/PulseEdit-<VERSION>-macOS.dmg (signed + notarized + stapled)

set -e
cd "$(dirname "$0")"

VERSION="${1:-$(python3 -c "import re; m=re.search(r'__version__\s*=\s*[\"\']([^\"\']+)[\"\']', open('app/__version__.py').read()); print(m.group(1))" 2>/dev/null || echo "0.0.0")}"
APP="dist/PulseEdit.app"
DMG="dist/PulseEdit-v${VERSION}-macOS.dmg"
IDENTITY="Developer ID Application: Abramo Benedetti (P4JYVWNR6H)"
KEYCHAIN_PROFILE="AC_PASSWORD"

if [ ! -d "$APP" ]; then
  echo "✗ $APP not found. Run ./notarize.sh first." >&2
  exit 1
fi

echo "▶ Removing any old DMG..."
rm -f "$DMG"

echo "▶ Building DMG with visual drag-to-Applications..."
create-dmg \
  --volname "Pulse Edit ${VERSION}" \
  --window-pos 200 120 \
  --window-size 640 400 \
  --icon-size 128 \
  --icon "PulseEdit.app" 160 200 \
  --hide-extension "PulseEdit.app" \
  --app-drop-link 480 200 \
  --no-internet-enable \
  "$DMG" \
  "$APP"

echo "▶ Codesigning DMG..."
codesign --force --sign "$IDENTITY" --timestamp "$DMG"

echo "▶ Submitting DMG to Apple notarization..."
xcrun notarytool submit "$DMG" --keychain-profile "$KEYCHAIN_PROFILE" --wait

echo "▶ Stapling notarization ticket to DMG..."
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo "✓ Done. Distributable DMG: $DMG"
ls -la "$DMG"
