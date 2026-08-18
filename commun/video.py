# commun/video.py
"""Lecture vidéo partagée par tous les jeux (Tk).

Le lecteur vient de client-dictee/services.py, où il avait été durci après un
bug de gel : Tkinter n'est pas thread-safe, donc le thread worker ne fait QUE
décoder/redimensionner, et tout le rendu Tk passe par le thread principal. Ce
code délicat est mutualisé ici plutôt que recopié dans chaque jeu.

Deux usages prêts à l'emploi par-dessus :
* `VideoBanner`  — zone 16/9 intégrée à un écran (bandeau du Hub), toujours
  muette (bandeau en boucle infinie, voir assets/videos/A_LIRE.txt) ;
* `IntroVideoWindow` — fenêtre pop-up 16/9 jouée une fois au démarrage d'un
  jeu, avec sa piste audio si `pygame` et `imageio_ffmpeg` sont disponibles.

`imageio` est importé de façon tolérante : un jeu sans cette dépendance (ou une
installation incomplète) affiche un cadre vide au lieu de refuser de démarrer.
Même logique pour `pygame`/`imageio_ffmpeg` côté son : sans eux, l'intro reste
muette plutôt que de planter (c'est d'ailleurs le cas du Hub, qui n'a pas
`pygame` en dépendance).
"""

import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
import tkinter as tk

from PIL import Image, ImageTk

try:
    import imageio
except ImportError:  # pragma: no cover - dépend de l'installation du poste
    imageio = None

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - dépend de l'installation du poste
    imageio_ffmpeg = None

try:
    import pygame
except ImportError:  # pragma: no cover - dépend de l'installation du poste
    pygame = None

logger = logging.getLogger(__name__)


def audio_available() -> bool:
    """False si pygame ou imageio_ffmpeg manque : l'intro reste alors muette
    plutôt que d'échouer."""
    return pygame is not None and imageio_ffmpeg is not None


class _IntroAudioTrack:
    """Extrait (ffmpeg, via imageio_ffmpeg) puis joue (pygame) la piste audio
    d'une vidéo d'intro, en parallèle de son image.

    L'extraction tourne dans un thread à part pour ne pas retarder l'ouverture
    de la fenêtre. Un fichier trop court, sans piste audio, ou un ffmpeg en
    échec laisse simplement l'intro muette (log en info, pas d'exception)."""

    def __init__(self, video_path: str) -> None:
        self._stopped = False
        self._channel = None
        self._tmp_path: str | None = None
        threading.Thread(target=self._extract_and_play, args=(video_path,), daemon=True).start()

    def _extract_and_play(self, video_path: str) -> None:
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", video_path,
            "-vn", "-ac", "2", "-ar", "44100", tmp_path,
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            check=True, creationflags=creationflags)
        except (OSError, subprocess.CalledProcessError) as e:
            logger.info("Pas de piste audio exploitable pour %s (%s).", video_path, e)
            self._cleanup(tmp_path)
            return
        if self._stopped:
            self._cleanup(tmp_path)
            return
        self._tmp_path = tmp_path
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sound = pygame.mixer.Sound(tmp_path)
            if not self._stopped:
                self._channel = sound.play()
        except pygame.error as e:
            logger.warning("Lecture audio impossible pour %s: %s", video_path, e)

    def stop(self) -> None:
        self._stopped = True
        if self._channel is not None:
            self._channel.stop()
        if self._tmp_path:
            self._cleanup(self._tmp_path)

    @staticmethod
    def _cleanup(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

ASPECT_W, ASPECT_H = 16, 9


def video_available() -> bool:
    """False si imageio manque : les appelants affichent alors un cadre vide
    plutôt que de planter."""
    return imageio is not None


def sixteen_nine(width: int) -> int:
    """Hauteur 16/9 correspondant à une largeur donnée."""
    return max(1, int(round(width * ASPECT_H / ASPECT_W)))


def fit_16_9(max_width: int, max_height: int) -> tuple[int, int]:
    """Plus grand rectangle 16/9 tenant dans la zone proposée."""
    width = max(1, int(max_width))
    height = sixteen_nine(width)
    if height > max_height:
        height = max(1, int(max_height))
        width = max(1, int(round(height * ASPECT_W / ASPECT_H)))
    return width, height


class ControlledVideoPlayer:
    """Lit une vidéo dans un widget ``tk.Label`` sans jamais toucher Tk hors thread principal.

    Le thread worker se contente de décoder/redimensionner les frames (opérations
    CPU pures, thread-safe) et les dépose dans une ``queue.Queue``. Le rendu Tk
    (``label.config``, création de ``ImageTk.PhotoImage``) se fait exclusivement
    depuis le thread principal, piloté par ``label.after(...)``.

    Pour les vidéos qui bouclent (``loop=True``), le thread worker tente de
    pré-décoder l'intégralité des frames une seule fois (mise en cache). Si la
    vidéo est trop volumineuse pour tenir sous ``MAX_CACHE_BYTES``, on retombe
    sur un flux (streaming) frame par frame classique.

    ``on_finished`` n'est appelé que pour une lecture non bouclée arrivée à son
    terme — jamais après un ``stop()`` explicite, pour qu'une fermeture manuelle
    ne déclenche pas la suite prévue en fin de vidéo.
    """

    # Plafond mémoire pour le cache de frames pré-décodées (frames redimensionnées,
    # RGB 3 octets/pixel). Au-delà, on repasse en streaming pour éviter d'exploser la RAM.
    MAX_CACHE_BYTES = 64 * 1024 * 1024  # 64 Mo
    QUEUE_MAXSIZE = 2
    POLL_INTERVAL_MS = 10

    def __init__(
        self,
        label: tk.Label,
        video_path: str,
        size: tuple[int, int],
        loop: bool = True,
        fps: int = 24,
        on_finished=None,
    ) -> None:
        self.label = label
        self.path = video_path
        self.size = size
        self.loop = loop
        self.fps = fps
        self.delay_s = 1.0 / self.fps if self.fps > 0 else 1.0 / 24
        self.thread: threading.Thread | None = None
        self.is_running = False
        self._on_finished = on_finished
        self._finished_sent = False
        self._frame_queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAXSIZE)
        self._poll_job: str | None = None
        self._current_photo: ImageTk.PhotoImage | None = None
        self._cache: list[ImageTk.PhotoImage] | None = None
        self._cache_index = 0
        self._cache_next_time = 0.0
        # Jeton de session : incrémenté à chaque play()/stop() pour invalider les
        # callbacks after() et les messages du thread worker devenus obsolètes.
        self._session = 0

    # ---- API publique ----
    def play(self) -> None:
        if self.is_running:
            return
        if imageio is None:
            logger.warning("imageio absent : lecture de %s impossible.", self.path)
            return
        self.is_running = True
        self._finished_sent = False
        self._session += 1
        session = self._session
        self._cache = None
        self._cache_index = 0
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        self.thread = threading.Thread(target=self._decode_worker, args=(session,), daemon=True)
        self.thread.start()
        self._schedule_poll(session)

    def stop(self) -> None:
        self.is_running = False
        self._session += 1  # invalide tout callback after() ou message worker en vol
        if self._poll_job is not None:
            try:
                self.label.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.2)
        self._cache = None

    # ---- Thread worker : décodage/redimensionnement uniquement, jamais de Tk ici ----
    def _decode_worker(self, session: int) -> None:
        try:
            if self.loop:
                cached = self._try_build_cache(session)
                if cached is not None:
                    self._post_cache(cached, session)
                    return
            self._stream_frames(session)
        except (OSError, ValueError, RuntimeError, StopIteration) as e:
            logger.warning("Erreur de lecture vidéo (%s): %s", self.path, e)
            self.is_running = False

    def _try_build_cache(self, session: int) -> list[Image.Image] | None:
        """Pré-décode toute la vidéo en mémoire si elle tient sous MAX_CACHE_BYTES."""
        reader = None
        frames: list[Image.Image] = []
        frame_cost = self.size[0] * self.size[1] * 3
        total_bytes = 0
        try:
            reader = imageio.get_reader(self.path)
            for frame in reader:
                if not self.is_running or session != self._session:
                    return None
                total_bytes += frame_cost
                if total_bytes > self.MAX_CACHE_BYTES:
                    return None  # trop volumineux : on laissera le streaming prendre le relais
                image = Image.fromarray(frame).resize(self.size, Image.Resampling.BILINEAR)
                frames.append(image)
        finally:
            if reader is not None:
                reader.close()
        return frames or None

    def _post_cache(self, frames: list[Image.Image], session: int) -> None:
        if not self.is_running or session != self._session:
            return
        self._frame_queue.put(("cache", frames))

    def _stream_frames(self, session: int) -> None:
        """Décode et cadence les frames sur une horloge absolue (pas de dérive)."""
        reader = None
        try:
            reader = imageio.get_reader(self.path)
            while self.is_running and session == self._session:
                start = time.monotonic()
                frame_index = 0
                produced_any = False
                for frame in reader:
                    if not self.is_running or session != self._session:
                        return
                    produced_any = True
                    image = Image.fromarray(frame).resize(self.size, Image.Resampling.BILINEAR)
                    target_time = start + frame_index * self.delay_s
                    now = time.monotonic()
                    if target_time > now:
                        time.sleep(target_time - now)
                    frame_index += 1
                    try:
                        self._frame_queue.put(("frame", image), timeout=1.0)
                    except queue.Full:
                        pass  # le thread principal est en retard : on laisse tomber cette frame
                if not self.loop or not produced_any:
                    self.is_running = False
                    return
        finally:
            if reader is not None:
                reader.close()

    # ---- Thread principal : rendu Tk exclusivement ici ----
    def _schedule_poll(self, session: int) -> None:
        # Volontairement sans test sur `is_running` : une fois le worker terminé,
        # il reste des frames dans la file à afficher, puis la fin à signaler.
        if session != self._session:
            return
        try:
            self._poll_job = self.label.after(self.POLL_INTERVAL_MS, self._poll, session)
        except tk.TclError:
            pass

    def _poll(self, session: int) -> None:
        self._poll_job = None
        if session != self._session:
            return
        try:
            kind, payload = self._frame_queue.get_nowait()
        except queue.Empty:
            if not self.is_running:
                self._notify_finished(session)
            else:
                self._schedule_poll(session)
            return
        if kind == "cache":
            self._cache = [ImageTk.PhotoImage(img) for img in payload]
            self._cache_index = 0
            self._cache_next_time = time.monotonic()
            self._play_cache(session)
            return
        self._show_image(payload)
        self._schedule_poll(session)

    def _notify_finished(self, session: int) -> None:
        """Fin de lecture atteinte naturellement (file vidée, worker terminé).
        Appelé une seule fois par lecture."""
        if self._finished_sent or session != self._session:
            return
        self._finished_sent = True
        if self._on_finished:
            try:
                self._on_finished()
            except tk.TclError:
                pass

    def _show_image(self, pil_image: Image.Image) -> None:
        try:
            photo = ImageTk.PhotoImage(pil_image)
            self.label.config(image=photo)
            self.label.image = photo  # garde-fou anti-GC : référence conservée sur le widget
            self._current_photo = photo
        except tk.TclError:
            pass

    def _play_cache(self, session: int) -> None:
        if not self.is_running or session != self._session or not self._cache:
            return
        try:
            photo = self._cache[self._cache_index]
            self.label.config(image=photo)
            self.label.image = photo  # garde-fou anti-GC
            self._current_photo = photo
        except tk.TclError:
            return
        self._cache_index = (self._cache_index + 1) % len(self._cache)
        self._cache_next_time += self.delay_s
        now = time.monotonic()
        # Resynchronise si on a beaucoup dérivé (ex : mise en veille système)
        if self._cache_next_time < now - self.delay_s:
            self._cache_next_time = now
        delay_ms = max(0, int((self._cache_next_time - now) * 1000))
        try:
            self._poll_job = self.label.after(delay_ms, self._play_cache, session)
        except tk.TclError:
            pass


class VideoBanner(tk.Frame):
    """Zone 16/9 intégrée à un écran, qui lit une vidéo en boucle si le fichier
    existe. Sinon elle garde sa place et affiche un repère discret : l'écran ne
    change pas de forme selon qu'une vidéo a été déposée ou non."""

    TARGET_FPS = 16

    def __init__(self, master, video_path: str = None, width: int = 640,
                 placeholder: str = "", bg: str = "#000000", fg: str = "#4f6287",
                 font=None, **kw) -> None:
        height = sixteen_nine(width)
        super().__init__(master, width=width, height=height, bg=bg, **kw)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._size = (width, height)
        self._player: ControlledVideoPlayer | None = None
        self.label = tk.Label(self, bg=bg, fg=fg, text="", font=font)
        self.label.pack(fill=tk.BOTH, expand=True)
        self.set_video(video_path, placeholder)

    def set_video(self, video_path: str = None, placeholder: str = "") -> None:
        self.stop()
        if video_path and os.path.exists(video_path) and video_available():
            self.label.config(text="", image="")
            self._player = ControlledVideoPlayer(
                self.label, video_path, self._size, loop=True, fps=self.TARGET_FPS)
            self._player.play()
        else:
            self.label.config(image="", text=placeholder)

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player = None


class IntroVideoWindow(tk.Toplevel):
    """Pop-up 16/9 jouée UNE fois au démarrage d'un jeu, puis refermée.

    Toujours interruptible (clic, Échap, Entrée, Espace) : une intro qu'on ne
    peut pas passer devient pénible dès la deuxième partie. `on_close` est
    appelé exactement une fois, que la vidéo soit allée au bout ou non, pour que
    l'appelant enchaîne sans avoir à gérer les deux cas.
    """

    TARGET_FPS = 24
    MAX_WIDTH = 960
    SCREEN_RATIO = 0.6  # part de l'écran occupée au maximum

    def __init__(self, parent, video_path: str, on_close=None, bg: str = "#000000",
                 skip_hint: str = "Clique ou appuie sur Échap pour passer",
                 hint_fg: str = "#4f6287", font=None) -> None:
        super().__init__(parent)
        self.overrideredirect(True)   # pas de barre de titre : c'est une intro, pas une fenêtre
        self.configure(bg=bg)
        self.attributes("-topmost", True)
        self._on_close = on_close
        self._closed = False

        max_w = min(self.MAX_WIDTH, int(self.winfo_screenwidth() * self.SCREEN_RATIO))
        max_h = int(self.winfo_screenheight() * self.SCREEN_RATIO)
        width, height = fit_16_9(max_w, max_h)

        self.label = tk.Label(self, bg=bg, width=width, height=height)
        self.label.pack()
        self.label.configure(width=0, height=0)  # dimensionné par l'image, pas par le texte
        self.hint = tk.Label(self, text=skip_hint, bg=bg, fg=hint_fg, font=font)
        self.hint.pack(fill=tk.X, pady=(4, 6))

        self.geometry(f"{width}x{height + 28}")
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        for sequence in ("<Button-1>", "<Escape>", "<Return>", "<space>"):
            self.bind_all(sequence, lambda _e: self.close())

        self._player = ControlledVideoPlayer(
            self.label, video_path, (width, height), loop=False,
            fps=self.TARGET_FPS, on_finished=self.close)
        self._player.play()
        self._audio = _IntroAudioTrack(video_path) if audio_available() else None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for sequence in ("<Button-1>", "<Escape>", "<Return>", "<space>"):
            try:
                self.unbind_all(sequence)
            except tk.TclError:
                pass
        self._player.stop()
        if self._audio is not None:
            self._audio.stop()
        try:
            self.destroy()
        except tk.TclError:
            pass
        if self._on_close:
            self._on_close()


def play_intro(parent, video_path: str, on_close=None, **kw):
    """Ouvre l'intro si le fichier est là et que la lecture est possible.

    Retourne la fenêtre, ou None si l'intro est sautée — dans ce cas `on_close`
    est appelé immédiatement, pour que l'appelant ait le même enchaînement avec
    ou sans vidéo (un jeu ne doit jamais rester bloqué faute de fichier)."""
    if not video_path or not os.path.exists(video_path) or not video_available():
        if video_path and not os.path.exists(video_path):
            logger.info("Pas de vidéo d'intro (%s) : démarrage direct.", video_path)
        if on_close:
            on_close()
        return None
    return IntroVideoWindow(parent, video_path, on_close=on_close, **kw)
