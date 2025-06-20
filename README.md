# productspy

A simple Python library to grab product info like name and price from popular shopping sites like Amazon, Noon, AliExpress, Carrefour, and Extra.


## What it does

- Pulls out the product name, price, and URL from product pages.
- Supports multiple sites using different ways (HTML parsing, JSON-LD, or Playwright for sites that load content with JavaScript).
- Manages cookies so it can get around some security stuff on sites like AliExpress.
- Super easy to use — just give it a product link, and it’ll give you the info.


## How to install 

```bash
pip install -r requirements.txt
playwright install

## How to use

from productspy import get_product_info

url = "put your product URL here"
info = get_product_info(url)

print(f"Product Name: {info['name']}")
print(f"Price: {info['price']}")
print(f"URL: {info['url']}")

Supported sites

-Amazon
-Noon
-AliExpress
-Carrefour
-Extra


Cookies update (for AliExpress)
If cookies expire, the library will open a browser window so you can log in or verify yourself. Just follow the steps and close the browser when you’re done.

Contribute
Feel free to open an issue or pull request if you wanna help improve this.

