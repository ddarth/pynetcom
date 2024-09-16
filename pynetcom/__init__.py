# Импортируем основные классы и функции библиотеки
from pynetcom.rest_nce import RestNCE

# Версия библиотеки
__version__ = "0.1.0"

# Описание библиотеки
__doc__ = """
pynetcom - Python library for interacting with network devices and management systems
via REST API and CLI, supporting multiple vendors like Huawei, Nokia, and more.
"""

__all__ = ["RestNCE"]  # Список объектов, которые будут импортироваться по умолчанию
