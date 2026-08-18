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

        # Reglage serveur propre a chaque PC client : jamais distribue, jamais
        # ecrase par une mise a jour (voir server_client.save_server_config_override)
        "server_config.local.json",

        # Progression du joueur : propre a chaque PC.
        "user_profile.json",

        # Journal d'execution : genere sur le PC du joueur (voir commun/logs.py).
        # Sans cette exclusion, le journal du poste de dev partirait chez tout le
        # monde et ecraserait le leur a chaque mise a jour.
        "game.log",

        # Notes destinees au developpeur (ou deposer les videos et les avatars).
        "A_LIRE.txt",

        # Dev-only files, inutiles au joueur
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
        dirs[:] = [d for d in dirs if d not in files_to_ignore and not d.startswith('V')]

        for name in files:
            if name in files_to_ignore:
                continue

            file_path = os.path.join(root, name)
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
    game_directory = os.path.dirname(os.path.abspath(__file__))
    commun_directory = os.path.join(game_directory, "..", "commun")

    manifest_data = generate_manifest(game_directory, extra_dirs={"commun": commun_directory})

    manifest_path = os.path.join(game_directory, "manifest.json")
    with open(manifest_path, "w", encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=4, ensure_ascii=False)

    print(f"Manifest generated successfully at: {manifest_path}")
    print(f"Found {len(manifest_data)} files.")
