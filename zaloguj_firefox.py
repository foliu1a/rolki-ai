"""Logowanie do Higgsfield przez Firefoksa (tam user jest zalogowany na Higgsfield).

CLI Higgsfield samo otwiera DOMYSLNA przegladarke (przez rundll32). Odpalamy je z PATH
bez System32, wiec tego nie zrobi - wypisze tylko link do strony logowania, ktory
wylapujemy i otwieramy w Firefoksie. CLI dalej czeka na zatwierdzenie jak zwykle.

Uzycie: python zaloguj_firefox.py [--sucho] [--prywatne]
  --sucho     tylko pokaz link, nic nie otwieraj
  --prywatne  okno prywatne Firefoksa (bez zapamietanego konta - do przelogowania na inne konto)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HF = Path(os.environ["APPDATA"]) / "npm" / "node_modules" / "@higgsfield" / "cli" / "vendor" / "hf.exe"
FIREFOX = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Mozilla Firefox" / "firefox.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Mozilla Firefox" / "firefox.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Mozilla Firefox" / "firefox.exe",
]
LINK = re.compile(r"(file:///\S+|https?://\S+)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sucho = "--sucho" in sys.argv
    tryb = "-private-window" if "--prywatne" in sys.argv else "-new-tab"
    if not HF.is_file():
        print(f"Nie ma CLI Higgsfield w {HF}. Odpal instaluj.bat w rolki-ai.")
        return 1
    firefox = next((p for p in FIREFOX if p.is_file()), None)
    if not firefox:
        print("Nie ma Firefoksa - logowanie otworze w domyslnej przegladarce.", flush=True)

    env = dict(os.environ)
    env["PATH"] = str(HF.parent)  # bez System32 -> CLI nie otworzy domyslnej przegladarki
    proces = subprocess.Popen(
        [str(HF), "auth", "login", "--no-color"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
        text=True, encoding="utf-8", errors="replace")

    otwarte = False
    for linia in proces.stdout:
        znalezione = None if otwarte else LINK.search(linia)
        if not znalezione:
            print(linia, end="", flush=True)
            continue
        # linia z linkiem: zamiast "otworz ten plik" otwieramy go sami, w Firefoksie
        gdzie = "Firefoksie" if firefox else "domyslnej przegladarce"
        if sucho:
            print(f"[sucho] otworzylbym w {gdzie}: {znalezione.group(1)[:60]}...")
            proces.terminate()
            return 0
        if firefox:
            subprocess.Popen([str(firefox), tryb, znalezione.group(1)])
        else:
            os.startfile(znalezione.group(1))   # komputer bez Firefoksa (np. drugi PC): zwykla przegladarka
        print(f">> Otworzylem logowanie w {gdzie}. Zatwierdz tam i wroc do tego okna.", flush=True)
        otwarte = True
    return proces.wait()


if __name__ == "__main__":
    sys.exit(main())
