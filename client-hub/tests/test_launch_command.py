# tests/test_launch_command.py
"""Commande de lancement d'un jeu (client-hub/main.py::build_launch_command).

Fonction pure (aucun Popen, aucun fichier écrit) : vérifie que le mode
campagne ajoute bien `--campagne` aux arguments passés au jeu, et que le
mode solo ne l'ajoute pas — c'est ce drapeau qui fait se refermer le jeu tout
seul après sa mission (voir les mains.py des jeux)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as main_module  # noqa: E402

GAME = {"id": "maths", "dir": "../client-maths"}


def test_solo_command_has_no_campaign_flag():
    command = main_module.build_launch_command(GAME, campaign=False)
    assert "--campagne" not in command


def test_campaign_command_includes_campaign_flag():
    command = main_module.build_launch_command(GAME, campaign=True)
    assert "--campagne" in command


def test_command_targets_main_py():
    command = main_module.build_launch_command(GAME, campaign=True)
    assert "main.py" in command


def test_flag_is_the_last_argument():
    command = main_module.build_launch_command(GAME, campaign=True)
    assert command[-1] == "--campagne"
