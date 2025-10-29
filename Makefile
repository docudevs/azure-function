BUILD_DIR := build
PACKAGE_DIR := $(BUILD_DIR)/package
ZIP_NAME := docudevs-function.zip
UV := uv
RSYNC := rsync
ZIP := zip
EXPORTED_REQUIREMENTS := $(BUILD_DIR)/requirements.txt

COPY_EXCLUDES := \
	--exclude '.git' \
	--exclude '.venv' \
	--exclude '__pycache__' \
	--exclude '*.pyc' \
	--exclude 'local.settings.json' \
	--exclude 'build' \
	--exclude '*.md' \
	--exclude 'Makefile' \
	--exclude '*.json' \
	--exclude 'tests' \
	--exclude '.gitignore' \
	--exclude '.vscode'
	

.PHONY: zip clean prepare copy deps package

zip: clean prepare copy deps package
	@echo "Created $(BUILD_DIR)/$(ZIP_NAME)"

prepare:
	@mkdir -p "$(PACKAGE_DIR)/.python_packages/lib/site-packages"

copy:
	@$(RSYNC) -a $(COPY_EXCLUDES) ./ "$(PACKAGE_DIR)/"

deps: $(EXPORTED_REQUIREMENTS)
	@$(UV) pip install --target "$(PACKAGE_DIR)/.python_packages/lib/site-packages" --requirements "$(EXPORTED_REQUIREMENTS)"

$(EXPORTED_REQUIREMENTS):
	@mkdir -p "$(BUILD_DIR)"
	@$(UV) export --format requirements-txt --project . --no-hashes --output-file "$(EXPORTED_REQUIREMENTS)"

package:
	@cd "$(PACKAGE_DIR)" && $(ZIP) -r "../$(ZIP_NAME)" .

clean:
	@rm -rf "$(BUILD_DIR)"
