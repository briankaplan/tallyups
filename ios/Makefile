# TallyScanner iOS Build Makefile

.PHONY: all setup build archive upload clean icons help

SCHEME = TallyScanner
PROJECT = TallyScanner.xcodeproj
BUILD_DIR = ./build
ARCHIVE_PATH = $(BUILD_DIR)/$(SCHEME).xcarchive
IPA_PATH = $(BUILD_DIR)/$(SCHEME).ipa

help:
	@echo "TallyScanner iOS Build Commands"
	@echo "================================"
	@echo ""
	@echo "  make setup      - Install dependencies (fastlane, etc.)"
	@echo "  make icons      - Generate app icons and launch logos"
	@echo "  make build      - Build for testing"
	@echo "  make archive    - Create release archive"
	@echo "  make upload     - Upload to TestFlight"
	@echo "  make clean      - Clean build artifacts"
	@echo ""

setup:
	@echo "📦 Installing dependencies..."
	brew install fastlane imagemagick || true
	cd fastlane && bundle install || true
	@echo "✅ Setup complete"

icons:
	@echo "🎨 Generating app icons..."
	chmod +x scripts/generate_assets.sh
	cd scripts && ./generate_assets.sh

build:
	@echo "🔨 Building $(SCHEME)..."
	xcodebuild build \
		-scheme $(SCHEME) \
		-project $(PROJECT) \
		-destination "generic/platform=iOS" \
		-configuration Debug

archive:
	@echo "📦 Creating archive..."
	mkdir -p $(BUILD_DIR)
	xcodebuild archive \
		-scheme $(SCHEME) \
		-project $(PROJECT) \
		-archivePath $(ARCHIVE_PATH) \
		-destination "generic/platform=iOS" \
		-configuration Release

export: archive
	@echo "📤 Exporting IPA..."
	xcodebuild -exportArchive \
		-archivePath $(ARCHIVE_PATH) \
		-exportPath $(BUILD_DIR) \
		-exportOptionsPlist ExportOptions.plist

upload: export
	@echo "🚀 Uploading to TestFlight..."
	@echo "Please use Xcode Organizer or Transporter app to upload:"
	@echo "  $(IPA_PATH)"
	@echo ""
	@echo "Or use fastlane:"
	@echo "  fastlane beta"

testflight:
	@echo "🚀 Building and uploading to TestFlight..."
	fastlane beta

clean:
	@echo "🧹 Cleaning..."
	rm -rf $(BUILD_DIR)
	rm -rf ~/Library/Developer/Xcode/DerivedData/$(SCHEME)-*
	xcodebuild clean -scheme $(SCHEME) -project $(PROJECT)
	@echo "✅ Clean complete"

open:
	open $(PROJECT)

# CI/CD target
ci-build:
	xcodebuild build \
		-scheme $(SCHEME) \
		-project $(PROJECT) \
		-destination "platform=iOS Simulator,name=iPhone 15 Pro" \
		-configuration Debug \
		CODE_SIGNING_ALLOWED=NO

ci-test:
	xcodebuild test \
		-scheme $(SCHEME) \
		-project $(PROJECT) \
		-destination "platform=iOS Simulator,name=iPhone 15 Pro" \
		-configuration Debug \
		CODE_SIGNING_ALLOWED=NO
