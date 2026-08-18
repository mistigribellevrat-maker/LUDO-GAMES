# launcher.py
import os
import json
import hashlib
import requests
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.messagebox import showerror, showinfo

class GameLauncher:
    # TODO avant distribution reelle : heberger ce dossier (main.py, services.py,
    # ui_components.py, problems.py, assets/, commun/, manifest.json, ...) a cette
    # adresse et mettre a jour BASE_URL en consequence (meme principe que
    # client-dictee/launcher.py, qui pointe vers .../games1/).
    BASE_URL = "https://www.gregbellevrat.fr/games/games2/"
    MANIFEST_FILE = "manifest.json"
    GAME_EXECUTABLE = "main.py"

    def __init__(self, root):
        self.root = root
        self.root.title("Grille de Protection - Launcher")
        self.root.geometry("400x150")
        self.root.resizable(False, False)

        self.status_var = tk.StringVar(value="Prêt à vérifier les mises à jour...")
        self.progress_var = tk.DoubleVar()

        self._setup_ui()

    def _setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        status_label = ttk.Label(main_frame, textvariable=self.status_var, wraplength=380)
        status_label.pack(pady=(0, 10))

        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=5)

        self.action_button = ttk.Button(main_frame, text="Vérifier les mises à jour", command=self.start_update_process)
        self.action_button.pack(pady=10)

    def start_update_process(self):
        self.action_button.config(state=tk.DISABLED)
        self.root.update_idletasks()
        try:
            self.check_for_updates()
        except Exception as e:
            showerror("Erreur", f"Une erreur critique est survenue: {e}")
            self.root.destroy()

    def check_for_updates(self):
        self.status_var.set("Téléchargement du manifeste...")
        self.root.update_idletasks()

        try:
            remote_manifest = self.get_remote_manifest()
        except Exception as e:
            self.status_var.set("Erreur: Impossible de récupérer le manifeste distant.")
            showerror("Erreur de connexion", f"Impossible de télécharger le manifeste des fichiers. Vérifiez votre connexion internet.\n{e}")
            self.action_button.config(text="Réessayer", state=tk.NORMAL)
            return

        local_manifest = self.get_local_manifest()

        files_to_download = []
        for file_path, remote_hash in remote_manifest.items():
            if file_path not in local_manifest or local_manifest[file_path] != remote_hash:
                files_to_download.append(file_path)

        if not files_to_download:
            self.status_var.set("Le jeu est à jour !")
            self.launch_game()
        else:
            self.download_files(files_to_download, remote_manifest)

    def get_remote_manifest(self):
        url = self.BASE_URL + self.MANIFEST_FILE
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()

    def get_local_manifest(self):
        if not os.path.exists(self.MANIFEST_FILE):
            return {}
        with open(self.MANIFEST_FILE, "r", encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}

    def download_files(self, files, remote_manifest):
        total_files = len(files)
        for i, file_path in enumerate(files):
            self.status_var.set(f"Téléchargement de {os.path.basename(file_path)} ({i+1}/{total_files})...")
            self.progress_var.set((i / total_files) * 100)
            self.root.update_idletasks()

            # Ensure local directory exists
            local_dir = os.path.dirname(file_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir)

            try:
                self.download_file(file_path)
            except Exception as e:
                showerror("Erreur de téléchargement", f"Impossible de télécharger le fichier: {file_path}\n{e}")
                self.action_button.config(text="Réessayer", state=tk.NORMAL)
                return

        self.progress_var.set(100)
        self.status_var.set("Mise à jour terminée !")

        # Save the new manifest
        with open(self.MANIFEST_FILE, "w", encoding='utf-8') as f:
            json.dump(remote_manifest, f, indent=4)

        self.launch_game()

    def download_file(self, file_path):
        url = self.BASE_URL + file_path
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def install_dependencies(self):
        self.status_var.set("Installation des dépendances...")
        self.root.update_idletasks()
        try:
            # Use pip from the same python that is running the launcher
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        except subprocess.CalledProcessError as e:
            showerror("Erreur d'installation", f"Impossible d'installer les dépendances depuis requirements.txt.\n{e}")
            raise  # Re-raise the exception to stop the process
        except FileNotFoundError:
            showerror("Erreur", "pip n'est pas disponible. Assurez-vous que Python est correctement installé.")
            raise

    def launch_game(self):
        self.status_var.set("Lancement du jeu...")
        self.action_button.pack_forget()
        self.progress_bar.pack_forget()
        self.root.update_idletasks()

        try:
            self.install_dependencies()
            # main.py est le point d'entree. On prefere pythonw.exe (meme dossier
            # que l'interpreteur courant) a python.exe : sinon une fenetre
            # console noire reste ouverte derriere le jeu pendant toute la
            # partie. CREATE_NO_WINDOW couvre le cas ou pythonw est absent.
            interpreter = sys.executable
            pythonw = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
            if os.path.isfile(pythonw):
                interpreter = pythonw
            subprocess.Popen([interpreter, self.GAME_EXECUTABLE],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.root.after(1000, self.root.destroy) # Close launcher after a delay
        except Exception as e:
            showerror("Erreur de lancement", f"Impossible de démarrer le jeu.\nAssurez-vous que {self.GAME_EXECUTABLE} existe.\n{e}")
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = GameLauncher(root)
    root.mainloop()
