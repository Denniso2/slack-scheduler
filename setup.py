from setuptools import setup, find_packages

setup(
    name="slack-scheduler",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "pyyaml>=6.0.1",
        "python-dotenv>=1.0.0",
        "apscheduler>=3.10.0,<4.0.0",
    ],
    entry_points={
        "console_scripts": [
            "slack-scheduler=slack_scheduler.cli:main",
        ],
    },
    python_requires=">=3.10",
)
