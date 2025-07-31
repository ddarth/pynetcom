from setuptools import setup, find_packages
import platform
import sys

# Читаем README.md для long_description
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

install_requires = [
    'requests',
    'urllib3',
    'ncclient',
    'xmltodict'
]

# Определяем зависимости в зависимости от операционной системы
if platform.system() == 'Windows':
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        # Если находимся в виртуальном окружении
        install_requires.append('wexpect_venv')
    else:
        # Если в системной среде
        install_requires.append('wexpect')
else:
    install_requires.append('pexpect')

setup(
    name='pynetcom',
    version='0.1.5',
    description='Library for Huawei, Nokia network device API interactions',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ddarth/pynetcom",
    author='Dmitriy Kozlov',
    author_email="kdsarts@gmail.com",
    packages=find_packages(),
    install_requires=install_requires,
    python_requires='>=3.7',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Telecommunications Industry',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: System :: Networking',
        'Topic :: System :: Networking :: Monitoring',
        'Topic :: Software Development :: Libraries',
    ],
    keywords='networking huawei nokia rest cli netconf',
    package_data={
        'pynetcom': ['utils/*'],
    },
    zip_safe=False,
)
