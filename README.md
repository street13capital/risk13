## MT5 Intraday Risk Engine

This repo is an intraday risk engine to assist with risk management for my discretionary manual trading. The Python package mt5-mac is used to communicate with MetaTrader 5 running on my MacBook through Wine wrapper. I do not want to use a VPS or some API service to do it. I just want to run it locally.

So I use the mt5-mac package. Some minor modifications have to be made to work on my laptop and the mt5_mac folder has the modified package. You can find out more about mt5-mac package here [pypi.org/project/mt5-mac](https://pypi.org/project/mt5-mac). The package links to dead URLs on GitHub and the author's email is invalid too, not sure why.

For the risk engine, you can see source code at [risk_engine.py](https://github.com/street13capital/mt5_mac/blob/main/risk_engine.py) and its various parameters. There are other possible features like narrowing daily risk limit base on time left to end of trading session or profitability for the day, automated trailing stop, etc. For now I think they are better left done with discretionary evaluation.

### Key features of the risk engine
- trailing daily risk - close positions if exceed daily risk marked to peak balance
- trailing weekly risk - close positions if exceed weekly risk marked to peak balance
- automated cut loss - auto cut open trades if paper loss exceeds trade risk exposure
- outside capital - allow risk calculations where not all capital is in MT5 account
- next trade size - display next trade size accounting for remaining daily risk limit
- breakeven stop - get out of a trade if it goes to +0.5R and comes back to breakeven
- protective stops - progressively tighter trailing of trades at +2.5R, +4.0R, +6.5R

### Sample output of risk engine

```
[Intraday Risk Engine]
Maximum: 1234.56
Current: 1203.04
Equity:  1168.11
P&L:     -34.93
Size:    1.0
```

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
