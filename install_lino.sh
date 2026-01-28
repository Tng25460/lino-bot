#!/bin/bash

echo "Création de l'environnement virtuel..."
python3 -m venv .venv

echo "Activation de l'environnement virtuel..."
source .venv/bin/activate

echo "Mise à jour de pip..."
pip install --upgrade pip

echo "Installation des dépendances Python..."
pip install requests flask solana python-telegram-bot aiohttp

echo "Installation terminée !"
echo "Pour lancer le bot, active l'environnement virtuel avec :"
echo "  source .venv/bin/activate"
echo "Puis lance le bot avec :"
echo "  python -m src.main"
echo "Dans un autre terminal, lance le dashboard avec :"
echo "  python dashboard.py"
echo "Accède ensuite au dashboard via : http://localhost:5000"