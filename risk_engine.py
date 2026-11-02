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
last_printout_time = 0

def flatten_all_positions():
    positions = mt5.positions_get()
    if not positions:
        return

    for pos in positions:
        if pos.type == mt5.POSITION_TYPE_BUY:
            trade_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(pos.symbol).bid
        else:
            trade_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(pos.symbol).ask

        close_payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": trade_type,
            "position": pos.ticket,
            "price": price,
            "deviation": 20,
            "magic": 999999,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(close_payload)

# 1) connect to local MT5 instance running on macOS,
# using python keyring to securely store credentials
# terminal path override is needed to work vs the default using \\
windows_terminal_path = 'C:/Program Files/MetaTrader 5/terminal64.exe'
mt5.initialize(path=windows_terminal_path)
mt5_login = int(keyring.get_password('MT5_Account', 'login'))
mt5_password = keyring.get_password('MT5_Account', 'password')
mt5_server = keyring.get_password('MT5_Account', 'server')
mt5.login(mt5_login, mt5_password, mt5_server)
# initial clear screen before printing figures
os.system('cls' if os.name == 'nt' else 'clear')

# 2) set peak balance from data file or reset balance
# reset if UTC time starts a new day, ie Singapore time 8am
# that is a good reset time at the start of Asia time zone
current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
if os.path.exists(risk_data_file):
    with open(risk_data_file, "r") as f:
        last_saved_date, last_saved_balance, saved_weekly_balance = f.read().strip().split(",")
        weekly_peak_balance = float(saved_weekly_balance)
        last_reset_date = current_date
        if last_saved_date == current_date:
            daily_peak_balance = float(last_saved_balance)
        else:
            account = mt5.account_info()
            daily_peak_balance = account.balance
            with open(risk_data_file, "w") as f:
                f.write(f"{current_date},{daily_peak_balance},{weekly_peak_balance}")
else:
    account = mt5.account_info()
    daily_peak_balance = account.balance
    weekly_peak_balance = daily_peak_balance
    last_reset_date = current_date
    with open(risk_data_file, "w") as f:
        f.write(f"{current_date},{daily_peak_balance},{weekly_peak_balance}")

# 3) risk engine loop based on period polling_period_in_sec
try:
    while True:
        account = mt5.account_info()
        # 4) update daily peak balance and store it
        if account.balance > daily_peak_balance:
            daily_peak_balance = account.balance
            with open(risk_data_file, "w") as f:
                f.write(f"{current_date},{daily_peak_balance}")


        # print only periodically to reduce cpu usage
        current_time = time.time()
        if (current_time - last_printout_time) >= 30:
            print('\033[H\033[J[Intraday Risk Engine]\nMaximum:', daily_peak_balance,
                '\nCurrent:', account.balance, '\nEquity: ', account.equity,
                '\nP&L:    ', account.profit, '\n')
            last_printout_time = current_time

        # 4) update daily peak balance and store it
        if account.balance > daily_peak_balance:
            daily_peak_balance = account.balance
            with open(risk_data_file, "w") as f:
                f.write(f"{current_date},{daily_peak_balance}")

        # 5) check if trades exceeded trades risk limit
        # then flatten all open positions to force close
        if (account.profit < (-trade_risk_percentage * daily_peak_balance)):
            flatten_all_positions()
            print('[TRADE RISK EXCEEDED]')

        # 6) check if balance exceeded daily risk limit
        # then flatten all open positions if there is any
        if (account.equity < (1 - daily_risk_percentage) * daily_peak_balance):
            flatten_all_positions()
            print('[DAILY RISK EXCEEDED]')

        # delay to avoid useless computation cycles
        time.sleep(polling_period_in_sec)

except KeyboardInterrupt:
    # graceful exit for Control+C to kill risk engine process
    pass

finally:
    # 7) terminate engine process by sending shutdown to MT5
    mt5.shutdown()
