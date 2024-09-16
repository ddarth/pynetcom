from setuptools import setup, find_packages

setup(
    name='pynetcom',
    version='0.1.1',
    description='Library for Huawei, Nokia network device API interactions',
    long_description=open('README.md', encoding='utf-8').read(),  # Длинное описание (из README)
    long_description_content_type="text/markdown",
    url="https://github.com/ddarth/pynetcom",  # Ссылка на репозиторий
    author='Dmitriy Kozlov',
    author_email="kdsarts@gmail.com",  # Ваш email
    packages=find_packages(),
    install_requires=[
        'requests',
        'urllib3',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Intended Audience :: Network administrators',
        'Intended Audience :: System administrators',
        'Intended Audience :: Telecommunications Industry',
        'Topic :: System :: Networking',  
        'Topic :: Software Development :: Libraries', 
        'Environment :: Huawei :: NCE'
        'Environment :: Nokia :: NSP'
    ],
)
