from setuptools import setup, find_packages
import platform
import sys

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
    version='0.1.3',
    description='Library for Huawei, Nokia network device API interactions',
    long_description=open('README.md', encoding='utf-8').read(),  # Long description (from README)
    long_description_content_type="text/markdown",
    url="https://github.com/ddarth/pynetcom",
    author='Dmitriy Kozlov',
    author_email="kdsarts@gmail.com",
    packages=find_packages(),
    install_requires=install_requires,
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
    package_data={
        'pynetcom': ['utils/*'],  # Добавьте, если у вас есть дополнительные файлы, например, конфигурационные
    },
)
