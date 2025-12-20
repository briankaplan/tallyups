#!/bin/bash

# TallyScanner Asset Generator
# Requires ImageMagick: brew install imagemagick

set -e

ASSETS_DIR="../TallyScanner/Resources/Assets.xcassets"
ICON_DIR="$ASSETS_DIR/AppIcon.appiconset"
LAUNCH_DIR="$ASSETS_DIR/LaunchLogo.imageset"

echo "🎨 TallyScanner Asset Generator"
echo "================================"
echo ""

# Check for ImageMagick
if ! command -v convert &> /dev/null; then
    echo "❌ ImageMagick not found!"
    echo "   Install with: brew install imagemagick"
    exit 1
fi

# Create directories
mkdir -p "$ICON_DIR"
mkdir -p "$LAUNCH_DIR"

echo "📱 Generating App Icon (1024x1024)..."

# Generate App Icon - Receipt scanner design
convert -size 1024x1024 xc:'#0D1117' \
  \( -size 1024x1024 xc:none \
     -fill 'none' -stroke '#00FF88' -strokewidth 50 \
     -draw "roundrectangle 212,137 812,887 40,40" \
  \) -composite \
  \( -size 1024x1024 xc:none \
     -fill '#00FF88' \
     -draw "rectangle 300,280 724,320" \
     -draw "rectangle 300,400 650,440" \
     -draw "rectangle 300,520 700,560" \
     -draw "rectangle 300,640 550,680" \
     -draw "rectangle 300,760 620,800" \
  \) -composite \
  \( -size 1024x1024 xc:none \
     -fill '#00FF88' \
     -draw "polygon 750,700 900,850 750,1000 600,850" \
  \) -composite \
  "$ICON_DIR/AppIcon.png"

echo "✅ App icon generated"

# Update App Icon Contents.json
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

echo ""
echo "🚀 Generating Launch Logo..."

# Generate Launch Logo - Simple receipt icon
# 1x (100px)
convert -size 100x100 xc:none \
  -fill '#00FF88' \
  -draw "roundrectangle 10,5 90,95 5,5" \
  -fill '#0D1117' \
  -draw "rectangle 25,25 75,35" \
  -draw "rectangle 25,45 65,55" \
  -draw "rectangle 25,65 70,75" \
  "$LAUNCH_DIR/LaunchLogo.png"

# 2x (200px)
convert -size 200x200 xc:none \
  -fill '#00FF88' \
  -draw "roundrectangle 20,10 180,190 10,10" \
  -fill '#0D1117' \
  -draw "rectangle 50,50 150,70" \
  -draw "rectangle 50,90 130,110" \
  -draw "rectangle 50,130 140,150" \
  "$LAUNCH_DIR/LaunchLogo@2x.png"

# 3x (300px)
convert -size 300x300 xc:none \
  -fill '#00FF88' \
  -draw "roundrectangle 30,15 270,285 15,15" \
  -fill '#0D1117' \
  -draw "rectangle 75,75 225,105" \
  -draw "rectangle 75,135 195,165" \
  -draw "rectangle 75,195 210,225" \
  "$LAUNCH_DIR/LaunchLogo@3x.png"

echo "✅ Launch logos generated"

# Update Launch Logo Contents.json
cat > "$LAUNCH_DIR/Contents.json" << 'EOF'
{
  "images" : [
    {
      "filename" : "LaunchLogo.png",
      "idiom" : "universal",
      "scale" : "1x"
    },
    {
      "filename" : "LaunchLogo@2x.png",
      "idiom" : "universal",
      "scale" : "2x"
    },
    {
      "filename" : "LaunchLogo@3x.png",
      "idiom" : "universal",
      "scale" : "3x"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
EOF

echo ""
echo "================================"
echo "✅ All assets generated!"
echo ""
echo "Generated files:"
echo "  - $ICON_DIR/AppIcon.png (1024x1024)"
echo "  - $LAUNCH_DIR/LaunchLogo.png (100x100)"
echo "  - $LAUNCH_DIR/LaunchLogo@2x.png (200x200)"
echo "  - $LAUNCH_DIR/LaunchLogo@3x.png (300x300)"
echo ""
echo "📱 Ready for TestFlight!"
