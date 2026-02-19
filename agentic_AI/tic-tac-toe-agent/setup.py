from setuptools import setup, find_packages

setup(
    name='tic-tac-toe-agent',
    version='0.1.0',
    author='Your Name',
    author_email='your.email@example.com',
    description='An agentic AI that plays Tic Tac Toe using OpenAI Gym',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'gym',
        'numpy',
        'matplotlib'  # Add any other dependencies here
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)