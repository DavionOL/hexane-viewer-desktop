"""Einstiegspunkt für das gepackte Programm (PyInstaller)."""
import multiprocessing

from hexane_desk.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()          # nötig, damit Arbeitsprozesse im gepackten Programm starten (Windows/macOS)
    main()
