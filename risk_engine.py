import os
import time
from datetime import datetime, timezone
import keyring
import mt5_mac as mt5

# parameters for risk engine
trade_risk_percentage = 0.020
daily_risk_percentage = 0.067
weekly_risk_percentage = 0.200
polling_period_in_sec = 0.500
risk_data_file = 'risk_engine.txt'

last_reset_date = None
daily_peak_balance = None
weekly_peak_balance = None

def flatten_all_positions():
    pass

# 1) connect to local MT5 instance running on macOS,
# using python keyring to securely store credentials
# terminal path override is needed to work vs the default using \\
windows_terminal_path = 'C:/Program Files/MetaTrader 5/terminal64.exe'
mt5.initialize(path=windows_terminal_path)
mt5_login = int(keyring.get_password('MT5_Account', 'login'))
mt5_password = keyring.get_password('MT5_Account', 'password')
mt5_server = keyring.get_password('MT5_Account', 'server')
mt5.login(mt5_login, mt5_password, mt5_server)

# 2) set peak balance from data file or reset balance
# reset if UTC time starts a new day, ie Singapore time 8am
# that is a good reset time at the start of Asia time zone
current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
if os.path.exists(risk_data_file):
    with open(risk_data_file, "r") as f:
        last_saved_date, last_saved_balance = f.read().strip().split(",")
        if last_saved_date == current_date:
            daily_peak_balance = float(last_saved_balance)
            last_reset_date = current_date
        else:
            account = mt5.account_info()
            daily_peak_balance = account.balance
            last_reset_date = current_date
            with open(risk_data_file, "w") as f:
                f.write(f"{current_date},{account.balance}")
else:
    account = mt5.account_info()
    daily_peak_balance = account.balance
    last_reset_date = current_date
    with open(risk_data_file, "w") as f:
        f.write(f"{current_date},{account.balance}")

# 3) risk engine loop based on period polling_period_in_sec
try:
    while True:
        account = mt5.account_info()
        os.system('cls' if os.name == 'nt' else 'clear')
        # print('[', daily_peak_balance, account.balance, account.equity, account.profit, ']')
        print('[INTRADAY RISK ENGINE]')
        print('Peak:   ', daily_peak_balance)
        print('Current:', account.balance)
        print('Equity: ', account.equity)
        print('P&L:    ', account.profit)

        # 4) update daily peak balance and store it
        if account.balance > daily_peak_balance:
            daily_peak_balance = account.balance
            with open(risk_data_file, "w") as f:
                f.write(f"{current_date},{daily_peak_balance}")

        # 5) check if trades exceeded trades risk limit
        # then flatten all open positions to force close
        if (account.profit < (-trade_risk_percentage * daily_peak_balance)):
            print('[TRADE RISK EXCEEDED]')
            flatten_all_positions()

        # 6) check if balance exceeded daily risk limit
        # then flatten all open positions if there is any
        if (account.equity < (1 - daily_risk_percentage) * daily_peak_balance):
            print('[DAILY RISK EXCEEDED]')
            flatten_all_positions()

        # delay to avoid useless computation cycles
        time.sleep(polling_period_in_sec)

except KeyboardInterrupt:
    # graceful exit for Control+C to kill risk engine process
    pass

# 7) terminate engine process by sending shutdown to MT5
mt5.shutdown()
