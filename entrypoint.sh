#!/bin/bash

# Exit immediately on errors, undefined variables, or failed pipelines
set -euo pipefail

# Define the application directory
APP_DIR="/smart-agri-tech"

# Change to the application directory
echo "Navigating to the application directory: $APP_DIR"
cd "$APP_DIR"

# Install required dependencies
if [ -f "requirements.txt" ]; then
    echo "Found requirements.txt. Installing dependencies..."
    pip3 install --quiet --no-cache-dir -r requirements.txt
    echo "Dependencies successfully installed."
else
    echo "Error: requirements.txt not found! Skipping dependency installation."
fi

# Run the table creation script
if [ -f "create_tables.py" ]; then
    echo "Found create_tables.py. Running the table creation script..."
    python create_tables.py
    echo "Table creation script executed successfully."
else
    echo "Error: create_tables.py not found! Skipping table creation."
fi

# Check if a command is provided and execute it
if [ $# -gt 0 ]; then
    echo "Executing provided command: $*"
    exec "$@"
else
    echo "No command provided. Exiting script."
fi
