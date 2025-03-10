import os
from pathlib import Path

from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))
sample_dir = Path("traffic") / "data" / "samples"

try:
    # Get the long description from the README file
    with open(os.path.join(here, "readme.md"), encoding="utf-8") as f:
        long_description = f.read()
except FileNotFoundError:
    # This exception is a problem when launching tox
    # Could not find a better workaround
    # Forcing the inclusion of the readme in the archive seems overkill
    long_description = ""

setup(
    name="traffic",
    version="1.2.1b0",
    author="Xavier Olive",
    author_email="git@xoolive.org",
    url="https://github.com/burcturkoglu/traffic/",
    license="MIT",
    description="A toolbox for manipulating and analysing air traffic data",
    long_description=long_description,
    # https://dustingram.com/articles/2018/03/16/markdown-descriptions-on-pypi
    long_description_content_type="text/markdown",
    entry_points={
        "console_scripts": ["traffic=traffic.console:main"],
        "traffic.plugins": [
            "Bluesky = traffic.plugins.bluesky",
            "CesiumJS = traffic.plugins.cesiumjs",
            "Leaflet = traffic.plugins.leaflet",
        ],
    },
    packages=find_packages(),
    package_data={
        "traffic.data.airspaces": ["firs.json"],
        "traffic.data.samples": list(
            file.relative_to(sample_dir).as_posix()
            for file in sample_dir.glob("**/*.json.gz")
        ),
        "traffic": [
            os.path.join("..", "icons", f)
            for f in os.listdir(os.path.join("icons"))
            if f.startswith("travel")
        ],
    },
    python_requires=">=3.6",
    install_requires=[
        "numpy",
        "scipy",
        "matplotlib",
        "pandas",
        "pyproj",  # required to build cartopy from source (better be explicit)
        "Cartopy",
        "Shapely",
        "requests",
        "appdirs",  # proper configuration directories
        "paramiko",  # ssh connections
        "typing_extensions",
        "PyQt5",
        "altair",  # interactive Vega plots
        "ipywidgets",  # IPython widgets for traffic
        "ipyleaflet",  # Leaflet for notebooks
        "tqdm>=4.28",  # progressbars
        "cartotools==1.0",
        "pyModeS>=2.0",
    ],
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 3 - Alpha",
        # Indicate who your project is intended for
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        # Pick your license as you wish (should match "license" above)
        "License :: OSI Approved :: MIT License",
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
)
