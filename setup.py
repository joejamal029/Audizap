from setuptools import setup, find_packages

setup(
    name="audizap",
    version="1.0.0",
    description="Parallel music downloader & metadata pipeline with canonical catalog decoupling, multi-tier audio fallback cascade, in-file synchronized lyrics, and modern GUI.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Ajpop3y",
    url="https://github.com/joejamal029/Audizap",
    packages=find_packages(),
    py_modules=["cli", "gui"],
    install_requires=[
        "spotdl>=4.2.0",
        "customtkinter>=6.0.0",
        "yt-dlp>=2026.08.01",
        "mutagen>=1.48.0",
        "syncedlyrics>=1.0.0",
        "soundcloud-v2>=1.7.0",
        "rich>=13.9.0",
        "requests>=2.31.0",
    ],
    entry_points={
        "console_scripts": [
            "audizap=cli:main",
            "audizap-gui=gui:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Multimedia :: Sound/Audio",
    ],
    python_requires=">=3.10",
)
