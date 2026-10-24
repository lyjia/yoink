# Old implementation. Do not copy from this.

Archived 2026-10-24. This is the original LLM-generated prototype, kept for
reference only. It never ran from a clean checkout (source imports PyQt6 while
requirements list PySide6), loaded yt-dlp via zipimport from a downloaded
zipapp, and carried a cx_Freeze dependency scanner to support that choice.

The rewrite drives the yt-dlp binary via QProcess and packages with Nuitka.
Nothing in this folder should be imported or copied into the new code.

Original README follows.

---

Yoink!

A simple gui for yt-dlp by Lyjia and some AI

I am using this project to get the hang of agentic software development a.k.a. "vibe coding". At time of writing weapons of choice are [Roo Code](https://github.com/RooVetGit/Roo-Code) paired with [Gemini Pro 2.5 (Preview)](https://deepmind.google/technologies/gemini/)

To run it:

`python main.py` at a command prompt 
