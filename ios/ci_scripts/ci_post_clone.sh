#!/bin/bash

# Xcode Cloud post-clone script
# This runs after Xcode Cloud clones your repo

echo "🚀 TallyScanner Xcode Cloud Build"
echo "=================================="

# Navigate to iOS directory
cd "$CI_PRIMARY_REPOSITORY_PATH/ios" || exit 1

# Print build info
echo "📱 Scheme: TallyScanner"
echo "🔢 Build: $CI_BUILD_NUMBER"
echo "📦 Bundle ID: com.tallyups.scanner"

# Any additional setup can go here
# For example, generating assets:
# if command -v convert &> /dev/null; then
#     ./scripts/generate_assets.sh
# fi

echo "✅ Pre-build setup complete"
