#!/bin/bash
# Pulse Edit — sign + notarize macOS .app
#
# Prerequisiti:
#   1. Developer ID Application certificate nel Login keychain
#   2. App-specific password salvata con `xcrun notarytool store-credentials lumika`
#      (one-time setup; chiede Apple ID + Team ID + app-specific pwd)
#   3. dist/PulseEdit.app già buildata da PyInstaller (./build.sh)
#
# Uso: ./notarize.sh

set -e
cd "$(dirname "$0")"

APP="dist/PulseEdit.app"
ZIP="dist/PulseEdit-macOS.zip"
IDENTITY="Developer ID Application: Abramo Benedetti (P4JYVWNR6H)"
ENTITLEMENTS="entitlements.plist"
KEYCHAIN_PROFILE="AC_PASSWORD"
BUNDLE_ID="com.abtools.pulseedit"

if [ ! -d "$APP" ]; then
  echo "✗ $APP not found. Run ./build.sh first." >&2
  exit 1
fi

echo "▶ Patching Info.plist (bundle ID + version)..."
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 1.5.1" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 1.5.1" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion 1.5.1" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1.5.1" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :NSHumanReadableCopyright 'Copyright © 2026 Abramo Benedetti'" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string 'Copyright © 2026 Abramo Benedetti'" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription 'Pulse Edit analizza file audio per generare beat markers.'" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Pulse Edit analizza file audio per generare beat markers.'" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :NSAppleEventsUsageDescription 'Pulse Edit invia comandi a DaVinci Resolve per importare i marker.'" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :NSAppleEventsUsageDescription string 'Pulse Edit invia comandi a DaVinci Resolve per importare i marker.'" "$APP/Contents/Info.plist"

echo "▶ Codesigning all binaries (deep, hardened runtime, entitlements)..."
# Sign every nested .dylib/.so first so the outer bundle signature seals them all.
find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm +111 \) -print0 \
  | xargs -0 -I{} codesign --force --options runtime --timestamp --sign "$IDENTITY" "{}" 2>/dev/null || true

# Then sign the app bundle itself with entitlements.
codesign --force --deep --options runtime --timestamp \
  --entitlements "$ENTITLEMENTS" \
  --sign "$IDENTITY" \
  "$APP"

echo "▶ Verifying signature..."
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -5

echo "▶ Creating zip for notarytool submit..."
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "▶ Submitting to Apple notarization (this can take 2-15 min)..."
xcrun notarytool submit "$ZIP" \
  --keychain-profile "$KEYCHAIN_PROFILE" \
  --wait

echo "▶ Stapling ticket to .app bundle..."
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "▶ Repackaging zip with stapled app..."
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "✓ Done. Notarized + stapled bundle: $APP"
echo "✓ Distributable zip: $ZIP"
