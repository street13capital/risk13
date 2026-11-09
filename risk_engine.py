import os
import csv
import math
from datetime import datetime, timezone
from decimal import Decimal
import time
import sys
import subprocess
import keyring
import mt5_mac as mt5

# parameters for risk engine

# trading capital outside brokerage account
# modify risk_engine.txt last field directly
# below is just to initialise the variable
# to create the initial risk_engine.txt file
capital_park_in_bank = 0

# risk limits to flatten positions
trade_risk_percentage = 0.010
daily_risk_percentage = 0.067
weekly_risk_percentage = 0.20

# time-based daily risk allocation
# trading window in UTC 24h format
# break risk to different sessions
distributed_daily_risk = True
trading_start_utc_time = '0900'
trading_end_utc_time = '2100'
total_trading_sessions = 3

# show trade size factoring risk limit
# i only implemented this for 1 asset
# because i'm only trading 1 asset
display_trade_size = True
trade_size_constant = 0.000222

# stops to limit loss and protect profit

# for eg if price moved +0.5R and goes back,
# exit breakeven to prevent cutting at -1.0R.
# could be price moved but not working out
# so the entry signal might be invalidated.
breakeven_stop = True
breakeven_setting = 0.5

# if price moved +1.5R trail stop with 1R.
# if price moved +2.5R exit positions when
# price retraces 0.5R from the peak profit.
# similarly +4.0R and +6.5R to lock profits,
# trailing even tighter with 0.25R and 0.13R.
protective_stop = True
protective_setting = [(1.5, 1.0),
                      (2.5, 0.5),
                      (4.0, 0.25),
                      (6.5, 0.13)]

# how often to check account status
polling_period_in_sec = 0.250

# data file to store capital peaks
risk_data_file = 'risk_engine.txt'

# log intraday equity for viewing
log_intraday_equity = True
display_equity_curve = True

# obviously need to log to display
if display_equity_curve:
    log_intraday_equity = True

# initialise remaining variables
daily_peak_balance = None
weekly_peak_balance = None
trade_peak_profit = 0
last_printout_time = 0

def flatten_all_positions():
    # uncomment return for development during trading
    # so that engine will not wrongly close positions
    # return

    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        return

    for pos in positions:
        if pos.type == mt5.POSITION_TYPE_BUY:
            trade_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(pos.symbol).bid
        else:
            trade_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(pos.symbol).ask

        close_payload = {
            'action': mt5.TRADE_ACTION_DEAL,
            'symbol': pos.symbol,
            'volume': pos.volume,
            'type': trade_type,
            'position': pos.ticket,
            'price': price,
            'deviation': 30,
            'magic': 999999,
            'type_time': mt5.ORDER_TIME_GTC,
            'type_filling': mt5.ORDER_FILLING_IOC,
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

# calculate trading hours in defined trading window
trading_start_hour = int(trading_start_utc_time[:2])
trading_start_minute = int(trading_start_utc_time[2:])
trading_end_hour = int(trading_end_utc_time[:2])
trading_end_minute = int(trading_end_utc_time[2:])
total_trading_hours = (60 * trading_end_hour + trading_end_minute - \
                       60 * trading_start_hour - trading_start_minute) / 60
trading_hours_per_session = total_trading_hours / total_trading_sessions

# 2) set peak balance from data file or reset balance
# reset if UTC time starts a new day, ie Singapore time 8am
# that is a good reset time at the start of Asia time zone
current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
if os.path.exists(risk_data_file):
    with open(risk_data_file, 'r') as f:
        last_saved_date, last_saved_balance, saved_weekly_balance, \
            saved_capital_in_bank = f.read().strip().split(',')
        weekly_peak_balance = float(saved_weekly_balance)
        capital_park_in_bank = float(saved_capital_in_bank)
        if last_saved_date == current_date:
            daily_peak_balance = float(last_saved_balance)
        else:
            # refresh daily peak balance on new day
            account = mt5.account_info()
            daily_peak_balance = account.balance + capital_park_in_bank
            # refresh weekly peak balance on new week
            if datetime.now(timezone.utc).weekday() == 0:
                weekly_peak_balance = daily_peak_balance
            with open(risk_data_file, 'w') as f:
                f.write(f'{current_date},{daily_peak_balance:.2f},'
                    f'{weekly_peak_balance:.2f},{capital_park_in_bank:.2f}')
else:
    account = mt5.account_info()
    daily_peak_balance = account.balance + capital_park_in_bank
    weekly_peak_balance = daily_peak_balance
    with open(risk_data_file, 'w') as f:
        f.write(f'{current_date},{daily_peak_balance:.2f},'
            f'{weekly_peak_balance:.2f},{capital_park_in_bank:.2f}')

# start equity curve process before entering risk engine loop
if display_equity_curve:
    subprocess.Popen(
        [sys.executable, 'equity_curve.py'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

# 3) risk engine loop based on polling_period_in_sec
try:
    while True:
        # get latest account figures at every cycle
        account = mt5.account_info()

        # 4) update daily peak balance and store it
        # then calculate daily and weekly risk floors
        if (account.balance + capital_park_in_bank) > daily_peak_balance:
            daily_peak_balance = account.balance + capital_park_in_bank
            if daily_peak_balance > weekly_peak_balance:
                weekly_peak_balance = daily_peak_balance
            with open(risk_data_file, 'w') as f:
                f.write(f'{current_date},{daily_peak_balance:.2f},'
                    f'{weekly_peak_balance:.2f},{capital_park_in_bank:.2f}')

        if not distributed_daily_risk:
            daily_risk_floor = (1 - daily_risk_percentage) * daily_peak_balance
            weekly_risk_floor = (1 - weekly_risk_percentage) * weekly_peak_balance
        else:
            # first check which trading session is the time now
            # then calculate risk floors to allocate risk capital
            current_time = datetime.now(timezone.utc)
            elapsed_trading_hours = (60 * current_time.hour + current_time.minute - \
                                     60 * trading_start_hour - trading_start_minute) / 60
            if elapsed_trading_hours < 0:
                elapsed_trading_hours = 0 # handle session start earlier
            limit_percentage = (elapsed_trading_hours + trading_hours_per_session) \
                               // trading_hours_per_session / total_trading_sessions
            limit_percentage = min(limit_percentage, 1.0) # handle session end later
            daily_risk_floor = (1 - limit_percentage * daily_risk_percentage) * daily_peak_balance
            weekly_risk_floor = (1 - weekly_risk_percentage) * weekly_peak_balance

        # 5) only print periodically to reduce cpu usage
        # if enabled, log intraday equity periodically
        current_time = time.time()
        if (current_time - last_printout_time) >= 30:
            # print risk notice once per print cycle
            risk_exceeded_printed = False

            # calculate and display trade size for next trade
            # only 1 asset, have to be modified for many assets
            # account for remaining daily risk for next trade
            if display_trade_size:
                available_risk_capital = (account.equity + capital_park_in_bank) - \
                                           max(daily_risk_floor, weekly_risk_floor)
                trade_risk_capital = trade_risk_percentage * daily_peak_balance
                next_trade_size = trade_size_constant * (account.equity + capital_park_in_bank)
                if available_risk_capital <= 0:
                    next_trade_size = 0
                elif available_risk_capital < trade_risk_capital:
                    next_trade_size = next_trade_size * available_risk_capital / trade_risk_capital
                trade_size_text = '\nSize:    ' + f'{Decimal(f'{next_trade_size:.2g}'):f}' + '\n'
            else:
                trade_size_text = '\n'

            # use special code to clear screen not slower OS I/O
            print('\033[H\033[J[Intraday Risk Engine]\nMaximum:', f'{daily_peak_balance:.2f}',
                '\nCurrent:', (f'{account.balance + capital_park_in_bank:.2f}'),
                '\nEquity: ', (f'{account.equity + capital_park_in_bank:.2f}'),
                '\nP&L:    ', f'{account.profit:.2f}', trade_size_text)
            last_printout_time = current_time

            if log_intraday_equity:
                with open('equity_curve.txt', mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), 
                        round(account.equity + capital_park_in_bank, 2)
                    ])

        # 6) check if trades exceeded trades risk limit
        # then flatten all open positions to force close
        # this effectively acts as stop loss at trade limit
        if account.profit < (-trade_risk_percentage * daily_peak_balance):
            flatten_all_positions()
            print('[TRADE RISK EXCEEDED]')

        # 7) check if equity exceeded daily risk limit
        # then flatten all open positions if there is any
        if weekly_risk_floor > daily_risk_floor:
            if (account.equity + capital_park_in_bank) < weekly_risk_floor:
                flatten_all_positions()
                if not risk_exceeded_printed:
                    risk_exceeded_printed = True
                    print('[WEEKLY RISK EXCEEDED]')
        elif (account.equity + capital_park_in_bank) < daily_risk_floor:
            flatten_all_positions()
            if not risk_exceeded_printed:
                risk_exceeded_printed = True
                if distributed_daily_risk:
                    print('[SESSION RISK EXCEEDED]')
                else:
                    print('[DAILY RISK EXCEEDED]')

        # 8) breakeven and protective stops to limit loss and protect profit
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            trade_peak_profit = 0
        else:
            trade_risk_amount = trade_risk_percentage * daily_peak_balance
            if account.profit > trade_peak_profit:
                trade_peak_profit = account.profit
            if breakeven_stop and (account.profit <= 0) and \
            (trade_peak_profit >= (breakeven_setting * trade_risk_amount)):
                flatten_all_positions()
                print('[BREAKEVEN STOP TRIGGERED]')
            elif protective_stop:
                for threshold in protective_setting:
                    if (trade_peak_profit >= (threshold[0] * trade_risk_amount)) and \
                    (account.profit <= (trade_peak_profit - (threshold[1] * trade_risk_amount))):
                        flatten_all_positions()
                        print(f'[{threshold[0]}R PROTECTIVE STOPPED]')
                        break

        # delay to avoid useless computation cycles
        time.sleep(polling_period_in_sec)

except KeyboardInterrupt:
    # graceful exit for Control+C to kill risk engine process
    pass

finally:
    # 9) terminate engine process by sending shutdown to MT5
    mt5.shutdown()

