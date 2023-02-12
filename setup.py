#!/usr/bin/env python

from setuptools import find_packages, setup

with open("README.md", "rt") as fh:
    long_description = fh.read()

dependencies = [
    # "chia-blockchain==1.6",
    "chia-blockchain @ git+https://github.com/Chia-Network/chia-blockchain.git@main",
    "packaging==23.0",
    # "hsms",
]

dev_dependencies = [
    # "chia-dev-tools @ git+https://github.com/Chia-Network/chia-dev-tools.git",
    "build",
    "coverage",
    "pre-commit",
    "pylint",
    "pytest",
    "pytest-asyncio>=0.18.1",  # require attribute 'fixture'
    "isort",
    "flake8",
    "mypy",
    "black==21.12b0",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "pyinstaller==5.0",
    "pytest",
    "pytest-asyncio",
    "pytest-env",
    "types-aiofiles",
    "types-click",
    "types-cryptography",
    "types-pkg_resources",
    "types-pyyaml",
    "types-setuptools",
    "types-docutils",
]

setup(
    name="chia-clawback-primitive",
    packages=find_packages(exclude=("tests",)),
    author="Geoff Walmsley",
    entry_points={
        "console_scripts": ["clawback = src.cli.main:main"],
    },
    package_data={
        "": ["*.clvm.hex", "*.clsp.hex"],
    },
    author_email="g.walmsley@chia.net",
    setup_requires=["setuptools_scm"],
    install_requires=dependencies,
    url="https://github.com/Chia-Network/chia-clawback-primitive",
    license="https://opensource.org/licenses/Apache-2.0",
    description="Tools and Puzzles to support payment claw backs on the Chia network",
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Security :: Cryptography",
    ],
    extras_require=dict(
        dev=dev_dependencies,
    ),
    project_urls={
        "Bug Reports": "https://github.com/Chia-Network/chia-clawback-primitive",
        "Source": "https://github.com/Chia-Network/chia-clawback-primitive",
    },
)
