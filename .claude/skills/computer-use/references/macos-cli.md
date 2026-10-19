# macOS CLI alternatives to GUI control

Deterministic, scriptable, and verifiable from output. Reach for these before computer use.

## Apps and files

```bash
open -a "Preview" ~/Desktop/report.pdf        # open a file in a specific app
open -b com.apple.TextEdit notes.txt          # by bundle id
mdfind -name "invoice 2026"                   # Spotlight search by name
mdfind 'kMDItemContentType == "com.adobe.pdf"' -onlyin ~/Documents
mdls -name kMDItemWhereFroms file.pdf         # metadata, e.g. download source
pbpaste | head; echo "text" | pbcopy          # clipboard (only when the task needs it)
```

## Screens and windows

```bash
screencapture -x out.png                      # silent full-screen capture (terminal needs Screen Recording)
screencapture -x -R 0,0,1280,800 region.png   # region capture
osascript -e 'tell application "System Events" to get name of every process whose visible is true'
osascript -e 'tell application "Finder" to get bounds of window of desktop'
```

## AppleScript app dictionaries (API-level, preferred over GUI scripting)

```bash
osascript -e 'tell application "Notes" to get name of every note of folder "Notes"'
osascript -e 'tell application "Calendar" to get name of every calendar'
osascript -e 'tell application "Finder" to get POSIX path of (target of front window as alias)'
```

The first run prompts the user to allow Automation for the terminal; that is the user's decision.
Writing actions (creating notes, events, moving files) follow the same confirmation rules as GUI
actions when they send, delete or overwrite.

## Shortcuts

```bash
shortcuts list
shortcuts run "Resize Images" --input-path in.png --output-path out.png
```

## Xcode and the iOS Simulator

```bash
xcrun simctl list devices available
xcrun simctl boot "iPhone 16"                                  # name or UDID
xcodebuild -scheme MyApp -destination 'platform=iOS Simulator,name=iPhone 16' -derivedDataPath build build
xcrun simctl install booted build/Build/Products/Debug-iphonesimulator/MyApp.app
xcrun simctl launch booted com.example.MyApp
xcrun simctl openurl booted "myapp://settings"                 # deep link instead of tapping
xcrun simctl io booted screenshot sim.png
xcrun simctl ui booted appearance dark                         # simulator appearance (not the Mac's settings)
xcrun simctl spawn booted log stream --predicate 'process == "MyApp"' --style compact   # app logs
```

Use computer use only for gestures and taps that deep links and launch arguments cannot reach.

## Native macOS app builds

```bash
xcodebuild -list                                               # schemes and targets
xcodebuild -scheme MyMacApp -configuration Debug -derivedDataPath build build
open build/Build/Products/Debug/MyMacApp.app
log stream --predicate 'process == "MyMacApp"' --style compact # runtime logs while you click
```
