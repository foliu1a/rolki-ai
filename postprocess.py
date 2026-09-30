# -*- coding: utf-8 -*-
"""Most do VideoRemixer - generowanie unikalnych wariantow gotowego pliku."""
import os
import shutil
import sys
import tempfile

KATALOG_SKRYPTU = os.path.dirname(os.path.abspath(__file__))
VIDEOREMIXER_DIR = os.path.normpath(os.path.join(KATALOG_SKRYPTU, "..", "VideoRemixer"))

if VIDEOREMIXER_DIR not in sys.path:
    sys.path.insert(0, VIDEOREMIXER_DIR)


def wygeneruj_warianty(plik_wejsciowy, folder_wyjsciowy, liczba_wariantow=10, **kwargs):
    """Generuje `liczba_wariantow` unikalnych wersji `plik_wejsciowy" do `folder_wyjsciowy`.

    Wymaga ffmpeg w PATH oraz obecnosci ..\\VideoRemixer obok tego projektu.
    kwargs przechodza do generate_glitch_cuts_multi (cuts_config, quality_config, ...).
    """
    try:
        from glitch_cuts_generator import generate_glitch_cuts_multi, get_video_duration
    except ImportError as e:
        raise RuntimeError(
            f"Nie znaleziono VideoRemixer w {VIDEOREMIXER_DIR} (albo brak ffmpeg). {e}"
        )

    if not os.path.isfile(plik_wejsciowy):
        raise FileNotFoundError(plik_wejsciowy)

    duration = get_video_duration(plik_wejsciowy)

    with tempfile.TemporaryDirectory(prefix="rolki_scena_") as scena_dir:
        cel = os.path.join(scena_dir, os.path.basename(plik_wejsciowy))
        shutil.copy2(plik_wejsciowy, cel)

        scenes_config = [{"folder": scena_dir, "target_duration": duration}]
        generate_glitch_cuts_multi(
            scenes_config=scenes_config,
            audio_path=None,
            output_folder=folder_wyjsciowy,
            num_variations=liczba_wariantow,
            **kwargs,
        )

    return sorted(os.listdir(folder_wyjsciowy))
