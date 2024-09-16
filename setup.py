from setuptools import setup, find_packages

setup(
    name='pynetcom',
    version='0.1.2',
    description='Library for Huawei, Nokia network device API interactions',
    long_description=open('README.md', encoding='utf-8').read(),  # Long description (from README)
    long_description_content_type="text/markdown",
    url="https://github.com/ddarth/pynetcom",
    author='Dmitriy Kozlov',
    author_email="kdsarts@gmail.com",
    packages=find_packages(),
    install_requires=[
        'requests',
        'urllib3',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Developers',
        'Intended Audience :: Telecommunications Industry',
        'Topic :: System :: Networking :: Monitoring',
        'Topic :: System :: Networking',  
        'Topic :: Software Development :: Libraries', 
    ],
)
