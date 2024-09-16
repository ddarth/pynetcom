# PyNetCom

`pynetcom` is a library designed for connecting to network switches and routers from various vendors via REST API and CLI, as well as for interacting with management systems such as Huawei NCE and Nokia NSP. The library allows you to execute commands, retrieve inventory data, and obtain alarm lists.

## Features

- Connect to network devices using REST API and CLI.
- Interact with management systems (e.g., Huawei NCE, Nokia NSP).
- Retrieve inventory data.
- Obtain alarm lists.
- Convenient token management for authorization.
- Automatic token refresh upon expiration.

## Installation

You can install the package using `pip`:

```bash
pip install pynetcom
```

## Development

To set up the development environment:

```bash
# Install development dependencies
pip install setuptools wheel twine

# Install the package locally
pip install .

# Create wheel and source 
pip install build twine
python -m build

```

## Running Examples

To run examples, follow these steps:

1. Clone the repository:

    ```bash
    git clone <repository_url>
    cd pynetcom
    ```

2. Set up a virtual environment:

    ```bash
    python -m venv .venv
    ```

3. Activate the virtual environment:

    - On Windows:

        ```bash
        .venv\Scripts\activate
        ```

    - On macOS/Linux:

        ```bash
        source .venv/bin/activate
        ```

4. Add your configuration data to config.py:
    ```bash
    cp examples/config.example.py examples/config.py
    vi examples/config.py
    ```
    ```python
    API_NCE_USER =  "your_nce_api_user"
    API_NCE_PASS = "your_nce_password"
    API_NCE_HOST = "https://your_nce_hostip:26335"
    ```

5. Run an example script:

    ```bash
    python examples/huawei_nce.py
    ```


## Usage

Here is an example of how to use the library:

```python
from pynetcom import RestNCE

# Initialize connection to NCE
nce = RestNCE(API_NCE_HOST, API_NCE_USER, API_NCE_PASS)

# Get subnets from NCE
nce.send_request("/restconf/v2/data/huawei-nce-resource-inventory:subnets")
items = nce.get_data()
print(items)
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

