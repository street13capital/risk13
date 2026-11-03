This repo is an intraday risk engine to assist with risk management for my discretionary manual intraday trading. The Python package mt5-mac is used to communicate with MetaTrader 5 running on my MacBook through Wine wrapper. I do not want to use a VPS or some API service to do it. I just want to run it locally.

So I use this mt5-mac package. Some minor modifications have to be made to work on my laptop and the mt5_mac folder are the modified files. You can find out more about mt5-mac package here [pypi.org/project/mt5-mac](https://pypi.org/project/mt5-mac). The package links to dead URLs on GitHub and the author's email is invalid too, not sure why.

For the risk engine, you can see source code of [risk_engine.py](https://github.com/street13capital/mt5_mac/blob/main/risk_engine.py) and the parameters. I've implemented trailing daily risk, trailing weekly risk, and automated stop loss. Sample output of the risk engine running:

```
[Intraday Risk Engine]
Maximum: 1234.56
Current: 1203.04
Equity:  1168.11
P&L:     -34.93
```

There are other implementable ideas like narrowing daily risk base on time left to end of the trading session, or profitability of the day, trailing stop, exit at multiple of risk, etc. But at least for now, I think they are better left done manually.

For the mt5-mac package, below is a minimal demo script to initialise, get account info, and end execution. The windows_terminal_path step is needed to make it work vs leaving it as default.

```py
import mt5_mac as mt5
windows_terminal_path = "C:/Program Files/MetaTrader 5/terminal64.exe"

mt5.initialize(path=windows_terminal_path)
mt5.login(1234567, "password", "server")

print(mt5.account_info())
# do whatever work needed to be done here
# API at https://pypi.org/project/mt5-mac/

mt5.shutdown()
```
