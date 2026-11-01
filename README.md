Minimal demo script to initialise, get account info, and end execution.

The `windows_terminal_path` step is needed to make it work vs default.

```py
import mt5_mac as mt5
windows_terminal_path = "C:/Program Files/MetaTrader 5/terminal64.exe"

mt5.initialize(path=windows_terminal_path)
mt5.login(1234567,"password","server")

print(mt5.account_info())

mt5.shutdown()
```
