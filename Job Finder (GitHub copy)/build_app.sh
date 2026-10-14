#!/bin/bash
# Rebuilds "Job Finder.app" in this folder from app/JobFinder.applescript.
cd "$(dirname "$0")"
rm -rf "Job Finder.app"
osacompile -o "Job Finder.app" app/JobFinder.applescript
cp static/icon.icns "Job Finder.app/Contents/Resources/applet.icns"
rm -f "Job Finder.app/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "Job Finder.app/Contents/Info.plist" 2>/dev/null
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.chase.jobfinder" "Job Finder.app/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.chase.jobfinder" "Job Finder.app/Contents/Info.plist"
codesign --force --deep -s - "Job Finder.app"
touch "Job Finder.app"
echo "Built Job Finder.app"
