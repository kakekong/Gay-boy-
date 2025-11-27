#!/usr/bin/env bash
set -e
echo "Updating packages..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git

PROJECT_DIR=$HOME/gorangen_bot
mkdir -p $PROJECT_DIR
echo "Copy repo into $PROJECT_DIR and run the following commands:"
echo "cd $PROJECT_DIR"
echo "python3 -m venv venv"
echo "source venv/bin/activate"
echo "pip install -r requirements.txt"
echo "export TG_TOKEN=your_token"
echo "export TG_CHATID=your_chatid"
echo "gunicorn bot.bot_server:app --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120"
