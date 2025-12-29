# paper-discussion

A Python project for managing paper discussions with automated periodic execution via GitHub Actions.

## Overview

This project contains a main Python script that runs periodically to process paper discussions. The script is automatically executed by GitHub Actions on a scheduled basis.

## Files

- `main.py` - Main Python script that processes paper discussions
- `requirements.txt` - Python dependencies (currently empty, add as needed)
- `.github/workflows/run-script.yml` - GitHub Actions workflow for periodic execution

## Usage

### Running Locally

To run the script manually:

```bash
python main.py
```

### Automated Execution

The script is automatically executed:
- Daily at 00:00 UTC (via cron schedule)
- On every push to the main branch
- Manually via GitHub Actions workflow dispatch

### Adding Dependencies

Add any required Python packages to `requirements.txt`:

```
requests>=2.31.0
pandas>=2.0.0
```

## GitHub Actions

The workflow is configured in `.github/workflows/run-script.yml` and includes:
- Python environment setup
- Dependency installation
- Script execution

You can manually trigger the workflow from the Actions tab in GitHub.