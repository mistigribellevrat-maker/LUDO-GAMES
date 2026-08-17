# generate_manifest.py
import os
import json
import hashlib

def generate_manifest(directory=".", extra_dirs=None):
    """
    Scans the directory to create a manifest of files with their SHA256 checksums.
    Ignores the launcher and manifest generation files themselves.

    `extra_dirs` optionally maps a manifest path prefix -> external directory to
    vendor into this game's distribution (e.g. the shared "commun/" package),
    so each player's install stays self-contained even though the source lives
    outside this game's own folder in the dev repo.
    """
    manifest = {}
    files_to_ignore = [
        # Launcher and manifest scripts
        "launcher.py",
        "generate_manifest.py",
        "manifest.json",
        "LANCER.bat",  # lanceur dev local (install + run), chemin de dev uniquement

        # Reglage serveur propre a chaque PC client : jamais distribue, jamais
        # ecrase par une mise a jour (voir server_client.save_server_config_override)
        "server_config.local.json",

        # Progression du joueur : propre a chaque PC. Si ce fichier etait distribue,
        # le launcher ecraserait la sauvegarde de chaque enfant par le profil du
        # poste de dev a chaque mise a jour du jeu.
        "user_profile.json",

        # Sensitive files
        ".env",

        # Dev-only files, inutiles au joueur
        ".env.example",
        ".gitignore",
        "pytest.ini",
        "requirements-dev.txt",
        ".coverage",

        # Common dev/VCS folders
        "__pycache__",
        ".git",
        ".idea",
        ".claude",
        ".pytest_cache",
        "tests",
        "venv",
        "temp_audio",  # cache audio TTS regenere a l'execution
    ]

    for root, dirs, files in os.walk(directory):
        # Remove ignored directories from traversal, including version backups like V1, V2, etc.
        dirs[:] = [d for d in dirs if d not in files_to_ignore and not d.startswith('V')]

        for name in files:
            if name in files_to_ignore:
                continue

            file_path = os.path.join(root, name)

            # Normalize path to use forward slashes for consistency across OS
            relative_path = os.path.relpath(file_path, directory).replace("\\", "/")

            try:
                with open(file_path, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                manifest[relative_path] = file_hash
            except IOError as e:
                print(f"Could not read file {file_path}: {e}")

    for prefix, ext_dir in (extra_dirs or {}).items():
        if not os.path.isdir(ext_dir):
            continue
        for root, dirs, files in os.walk(ext_dir):
            dirs[:] = [d for d in dirs if d not in files_to_ignore]
            for name in files:
                if name in files_to_ignore:
                    continue
                file_path = os.path.join(root, name)
                relative_path = f"{prefix}/{os.path.relpath(file_path, ext_dir)}".replace("\\", "/")
                try:
                    with open(file_path, "rb") as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                    manifest[relative_path] = file_hash
                except IOError as e:
                    print(f"Could not read file {file_path}: {e}")

    return manifest

if __name__ == "__main__":
    # Assumes the script is in the root directory of the game
    game_directory = os.path.dirname(os.path.abspath(__file__))
    commun_directory = os.path.join(game_directory, "..", "commun")

    manifest_data = generate_manifest(game_directory, extra_dirs={"commun": commun_directory})

    manifest_path = os.path.join(game_directory, "manifest.json")
    with open(manifest_path, "w", encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=4, ensure_ascii=False)

    print(f"Manifest generated successfully at: {manifest_path}")
    print(f"Found {len(manifest_data)} files.")
