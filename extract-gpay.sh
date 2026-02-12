#!/usr/bin/env bash
#
# extract-gpay.sh - Wrapper script for extract_gpay.py
#
# Simple shell wrapper to invoke the Google Pay PDF transaction extractor

set -euo pipefail

# Get the directory where this script resides
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/extract_gpay.py"

# Show help if requested
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $(basename "$0") <pdf_path> [OPTIONS]

Extract transaction data from Google Pay PDF statements and output structured JSON.

Arguments:
  pdf_path              Path to the Google Pay PDF statement

Options:
  -o, --output PATH     Output JSON file path (default: output/<filename>.json)
  -q, --quiet           Suppress verification output
  -h, --help            Show this help message

Examples:
  $(basename "$0") data/google-pay-statement.pdf
  $(basename "$0") data/statement.pdf --output my-transactions.json
  $(basename "$0") data/statement.pdf --quiet

EOF
    exit 0
fi

# Check if at least one argument is provided
if [[ $# -eq 0 ]]; then
    echo "Error: No PDF file specified" >&2
    echo "Use --help for usage information" >&2
    exit 1
fi

# Verify Python 3 is available
echo "Checking for python3..."
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed or not in PATH" >&2
    exit 1
fi
echo "  ✓ python3 found"

# Verify Python script exists
echo "Checking for extract_gpay.py..."
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo "Error: Python script not found: $PYTHON_SCRIPT" >&2
    exit 1
fi
echo "  ✓ extract_gpay.py found"

# Parse arguments to extract PDF path and output path for display
# Save original arguments
ORIGINAL_ARGS=("$@")

PDF_PATH=""
OUTPUT_PATH=""

i=1
while [[ $i -le ${#ORIGINAL_ARGS[@]} ]]; do
    arg="${ORIGINAL_ARGS[$((i-1))]}"
    case $arg in
        -o|--output)
            OUTPUT_PATH="${ORIGINAL_ARGS[$i]}"
            ((i++))
            ;;
        -q|--quiet)
            # Just note it, will be passed through
            ;;
        -h|--help)
            # Already handled above
            ;;
        *)
            if [[ -z "$PDF_PATH" ]] && [[ ! "$arg" =~ ^- ]]; then
                PDF_PATH="$arg"
            fi
            ;;
    esac
    ((i++))
done

# Print input file
if [[ -n "$PDF_PATH" ]]; then
    echo ""
    echo "Input file: $PDF_PATH"

    # Calculate output path if not specified
    if [[ -z "$OUTPUT_PATH" ]]; then
        # Extract filename without extension
        BASENAME=$(basename "$PDF_PATH" .pdf)
        BASENAME=$(basename "$BASENAME" .PDF)
        OUTPUT_PATH="output/${BASENAME}.json"
    fi

    echo "Output file: $OUTPUT_PATH"
    echo ""
fi

# Run the Python script with all original arguments and capture exit code
if python3 "$PYTHON_SCRIPT" "${ORIGINAL_ARGS[@]}"; then
    echo ""
    echo "Ok"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo "Error: Extraction failed with exit code $EXIT_CODE" >&2
    exit $EXIT_CODE
fi
