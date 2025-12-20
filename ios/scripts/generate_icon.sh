#!/bin/bash

# TallyScanner App Icon Generator
# Requires ImageMagick: brew install imagemagick

set -e

ICON_DIR="../TallyScanner/Resources/Assets.xcassets/AppIcon.appiconset"
OUTPUT_FILE="$ICON_DIR/AppIcon.png"

echo "🎨 Generating TallyScanner App Icon..."

# Create a 1024x1024 app icon using ImageMagick
# Dark background with green receipt scanner icon

convert -size 1024x1024 xc:'#0D1117' \
  -fill '#00FF88' \
  -stroke '#00FF88' \
  -strokewidth 8 \
  \( -size 600x750 xc:none \
     -fill 'none' -stroke '#00FF88' -strokewidth 40 \
     -draw "roundrectangle 0,0 600,750 30,30" \
     -draw "line 100,200 500,200" \
     -draw "line 100,350 400,350" \
     -draw "line 100,500 450,500" \
     -draw "line 100,650 300,650" \
  \) -gravity center -composite \
  \( -size 200x200 xc:none \
     -fill '#00FF88' \
     -draw "polygon 100,0 200,100 100,200 0,100" \
  \) -gravity southeast -geometry +80+80 -composite \
  -quality 100 \
  "$OUTPUT_FILE"

if [ -f "$OUTPUT_FILE" ]; then
  echo "✅ Icon generated: $OUTPUT_FILE"
  echo "   Size: $(identify -format '%wx%h' "$OUTPUT_FILE")"
else
  echo "❌ Failed to generate icon"
  exit 1
fi

# Update Contents.json
cat > "$ICON_DIR/Contents.json" << 'EOF'
{
  "images" : [
    {
      "filename" : "AppIcon.png",
      "idiom" : "universal",
      "platform" : "ios",
      "size" : "1024x1024"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
EOF

echo "✅ Contents.json updated"
echo ""
echo "📱 Icon ready for TestFlight!"
