from setuptools import find_packages, setup
from setuptools_scm import get_version

setup(
    name="web3deploy",
    version=get_version(),
    author="Cameron Wong",
    description="",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "python-decouple",
        "rlog @ https://github.com/camerondub/python-rlog/archive/master.zip#egg=rlog-0.0.1",
        "py-solc-x",
        "web3",
    ],
    entry_points={"console_scripts": ["web3deploy = web3deploy:deploy"]},
)
