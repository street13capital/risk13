"""RISK 13 INTRADAY RISK ENGINE FOR METATRADER 5 RUNNING ON MACOS"""
# https://github.com/street13capital/risk13/blob/master/LICENSE
# MIT License, Copyright 2026 苏昭鸣

import os
import csv
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN
from indicators import FastEMAEngine
import time
import sys
import subprocess
import keyring
import mt5_mac as mt5
import tty
import termios
import select
import atexit

# parameters for intraday risk engine

# micro trading option to trade 1/10 size
# for testing and development of engine
micro_trading_enabled = False

# light trading option to trade 1/2 size
# for testing and developing of engine
# micro trading will override this
light_trading_enabled = True

# time-based daily risk allocation
# trading window in UTC 24h format
# split risk to different sessions
distributed_daily_risk = True
trading_start_utc_time = '0000'
trading_end_utc_time = '2000'
total_trading_sessions = 5

# reduce terminal size to fit output
resize_terminal_window = True

# enable entry detection and execution
enable_auto_trade_entry_testing = True
enable_auto_trade_place_trades = True
auto_trade_reverse_signals = True
auto_trade_heuristics_switch = False

# set some min acct amount for auto trade
# in case infinte loop denial of service
# by sending failed orders repeatedly
account_autotrade_minimum_balance = 5

# obviously need below override to run code block
# and distributed daily risk to avoid deep drawdown
if enable_auto_trade_place_trades:
    enable_auto_trade_entry_testing = True
    distributed_daily_risk = True
# parameter to check at each timeframe
# eg 1-min, not every sub-second loop
last_entry_checked_bucket = -1

# enable keys to long, short, close trades
# b = buy (long), n = close, m = sell (short)
# x = emergency flatten and close all positions
# h = unwind least profitable position of stack
# (useful for exit when adding to winning trades)
# j = reverse trade direction with risk sizing
# ,./ = set cut loss to 25% 50% 100% trade risk
# k = toggle profit and protective stops on/off
# edit watchlist_symbols and selected_trade_symbol
# in the later section below to set what to trade
enable_keys_to_trade = True

# trading capital outside brokerage account
# modify risk_engine.txt last field directly
# below is just to initialise the variable
# to create the initial risk_engine.txt file
capital_park_in_bank = 0

# enable block against countertrend trades
block_countertrend_trades = True

# disable adding of trades to cap risk
disable_adding_trades = True

# cut at fraction of trade risk instead
# as price hit -0.382R before +0.382R
# so it might mean the bias is wrong
enable_tight_cut_loss = False
if enable_tight_cut_loss:
    cut_loss_multiplier = 0.382
else: 
    cut_loss_multiplier = 1.0

# risk limits to flatten positions
trade_risk_percentage = 0.010
daily_risk_percentage = 0.080
weekly_risk_percentage = 0.24
if micro_trading_enabled:
    trade_risk_percentage /= 10
    daily_risk_percentage /= 10
    weekly_risk_percentage /= 10
elif light_trading_enabled:
    trade_risk_percentage /= 2
    daily_risk_percentage /= 2
    weekly_risk_percentage /= 2

# show trade size factoring risk limit
display_trade_size = True

# show maximum balance for today
# show current account balance
# show current account equity
display_max_balance = True
display_balance = True
display_equity = True

# show current symbol trend bias
# based on EMAs on 5-min chart
display_trend_bias = True
trend_bias_timeframes = [('1-min', mt5.TIMEFRAME_M1, 60),
                         ('5-min', mt5.TIMEFRAME_M5, 300),
                         ('30-min', mt5.TIMEFRAME_M30, 1800)]

# set selected timeframe from above list
# 0 is the first one, 1 is the second one etc.
# stop loss points generally defined for 30-min
# which will be halved for 5-min timeframe,
# and one-quartered for 1-min timeframe.
# at the moment not providing option to
# switch timeframe while running to avoid
# changing trading plan because of market.
selected_trade_timeframe = 0

# multiplier to adjust stops and trade risk
if selected_trade_timeframe == 0:
    timeframe_multiplier = 0.25
elif selected_trade_timeframe == 1:
    timeframe_multiplier = 0.50
elif selected_trade_timeframe == 2:
    timeframe_multiplier = 1.00
trade_risk_percentage *= timeframe_multiplier

# define symbols with their parameters
# - lot size ratio relative to capital
# - point for stop loss at trade risk
# - points are adjusted for timeframe
# - for eg below is 45, 250, 125 points
# - pip for forex pairs, points for others
watchlist_symbols = [('EURUSD', 0.000222, 4.5 * timeframe_multiplier),
                     ('BTCUSD', 0.000040, 250 * timeframe_multiplier),
                     ('USTEC',  0.000080, 125 * timeframe_multiplier),
                     ('XAUUSD', 0.0000125, 8.0 * timeframe_multiplier)]

# set selected symbol from above watchlist
# 0 is the first one, 1 is second one etc
selected_trade_symbol = 1

# define list to track peak profits for symbols
trade_peak_profit = [0] * len(watchlist_symbols)

# define lists to track trades P&L for symbols
# for heuristics purpose of automated entries
account_balance_history = [[]] * len(watchlist_symbols)
trade_position_open = [False] * len(watchlist_symbols) 

# load selected trade symbol parameters
default_trade_symbol = watchlist_symbols[selected_trade_symbol][0]
trade_size_constant = watchlist_symbols[selected_trade_symbol][1]
default_stop_loss_pips = watchlist_symbols[selected_trade_symbol][2]
if micro_trading_enabled:
    trade_size_constant /= 10
elif light_trading_enabled:
    trade_size_constant /= 2

# define major forex pairs for stop loss calculation
FOREX_PAIRS = ['EURUSD', 'USDJPY', 'GBPUSD', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD']  

# stops to limit loss and protect profit

# for eg if price moved +0.382R and goes back,
# exit breakeven to avoid cut at normal cutloss.
# it could be price moved but not working out
# so the entry signal might be invalidated.
breakeven_stop = True
breakeven_setting = 0.382

# profit stops at pre-defined thresholds.
# rationale is if price moved by an amount
# but retraces back instead of continuing,
# it suggests the trend isn't that strong
# to switch to the trailing stop approach.
# the percentage is at how much of target
# after hitting before locking in profits.
# if 1.0 too easily triggered with 1 tick.
profit_stop = True
profit_stop_percentage = 0.618
profit_setting = [0.618, 0.786, 1.0, 1.25]

# if price moved +1.5R, exit positions when
# price retraces 0.5R from the peak profit.
# similarly for +4.0R, +6.5R to lock profits,
# trailing even tighter with 0.25R and 0.13R.
protective_stop = True
protective_setting = [(1.5, 0.5),
                      (4.0, 0.25),
                      (6.5, 0.13)]

# swing (or rogue) trading mode where no stops and
# limits are imposed other than weekly risk limit
# the trader has to do everything else manually
# - cut loss at very small risk doesn't make sense
# - not being able to add doesn't make any sense
# - limited by daily risk limit doesn't make sense
# - various trailing stops don't make any sense
# - desired setup is being able to hold overnight
# - and concentrate weekly risk on taking entries
# - weekly risk limit still applies and imposed
swing_trading_mode = False

# set of overrides for swing trading mode
if swing_trading_mode:
    # cannot send order from risk engine
    # sizes need to be decided manually
    # stop loss and trailing stops too
    # symbols might not be in watchlist
    enable_keys_to_trade = False
    display_trade_size = False

    # don't block multiple trade entries
    # this flag is irrelevant but setting
    # here in case lead to bug in future
    disable_adding_trades = False

    # set trade risk & daily risk to weekly risk %
    # this way, only weekly risk limit is imposed
    trade_risk_percentage = weekly_risk_percentage
    daily_risk_percentage = weekly_risk_percentage
    distributed_daily_risk = False

    # this is needed or trade could be cut at a
    # fraction of the expanded weekly risk limit
    enable_tight_cut_loss = False
    cut_loss_multiplier = 1.0

    # no automated trailing stops, set them manually
    breakeven_stop = False
    profit_stop = False
    protective_stop = False

# how often to check account status
polling_period_in_sec = 0.125

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
last_printout_time = 0
force_subloop_refresh = False
force_refresh_msg = ''

def flatten_all_positions(symbol=None):
    # uncomment return for development during trading
    # so that engine will not wrongly close positions
    # print('[FLATTENING POSITIONS]')
    # return

    positions = mt5.positions_get(symbol)
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

def open_new_trade(symbol, direction, lot_size, comment='', sl_pips=None, tp_pips=None):
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        return None

    # safeguard in case not in watchlist
    # and API call return execution error
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    # confirm there is price quotation
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return None

    # prepare parameters for API request
    # assume major forex pairs with USD
    # pip calculation vs cent for others
    # can add on here for minors later
    if symbol in FOREX_PAIRS:
        pip = symbol_info.point * 10
    else:
        pip = symbol_info.point * 100
    decimal_digits = symbol_info.digits
    is_buy = direction.upper() == 'BUY'
    price = tick.ask if is_buy else tick.bid
    trade_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    sl = round(price + (-1 if is_buy else 1) * sl_pips * pip, decimal_digits) if sl_pips else 0.0
    tp = round(price + (1 if is_buy else -1) * tp_pips * pip, decimal_digits) if tp_pips else 0.0

    deal_request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': symbol,
        'volume': float(lot_size),
        'type': trade_type,
        'price': price,
        'sl': sl,
        'tp': tp,
        'deviation': 10,
        'magic': 999999,
        'comment': comment,
        'type_time': mt5.ORDER_TIME_GTC,
        'type_filling': mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(deal_request)

def get_current_trend(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if (tick.bid > ema_data['ema44'] > ema_data['ema78']) and (ema_data['slope78'] > 0):
        symbol_trend_bias = 'BULLISH'
    elif (tick.bid < ema_data['ema78'] < ema_data['ema44']) and (ema_data['slope78'] < 0):
        symbol_trend_bias = 'BEARISH'

    elif (tick.bid < ema_data['ema44'] < ema_data['ema78']) and (ema_data['slope78'] < 0):
        symbol_trend_bias = 'BEARISH'
    elif (tick.bid > ema_data['ema78'] > ema_data['ema44']) and (ema_data['slope78'] > 0):
        symbol_trend_bias = 'BULLISH'

    elif ema_data['ema78'] < tick.bid < ema_data['ema44']:
        symbol_trend_bias = 'CHOPPY'
    elif ema_data['ema78'] > tick.bid > ema_data['ema44']:
        symbol_trend_bias = 'CHOPPY'

    else:
        symbol_trend_bias = 'UNKNOWN'
    return symbol_trend_bias

def price_zone_change(symbol, boundary, direction, latest_candles):
    if direction == 'ABOVE':
        if latest_candles[0].close < ema_data[boundary] \
        and latest_candles[1].close > ema_data[boundary]:
            return True
        else:
            return False

    elif direction == 'BELOW':
        if latest_candles[0].close > ema_data[boundary] \
        and latest_candles[1].close < ema_data[boundary]:
            return True
        else:
            return False

    else:
        return False

def ema_rejection_setup(symbol):
    # - sea land sky setup
    # - leaving sky zone
    # - leaving land zone
    # - entering sea zone
    # - direction of sea

    tick = mt5.symbol_info_tick(symbol)
    ema_data = ema_engine.fast_live_only(tick.bid)
    current_trend_bias = get_current_trend(symbol)

    latest_candles = mt5.copy_rates_from_pos(symbol, \
        trend_bias_timeframes[selected_trade_timeframe][1], 0, 3)
    if latest_candles is not None and len(latest_candles) == 3:
        if latest_candles[0][0] > latest_candles[-1][0]:
            latest_candles = latest_candles[::-1]

    if price_zone_change(symbol, 'ema13', 'ABOVE', latest_candles) \
    and (current_trend_bias == 'BULLISH'):
        return 'BUY'
    elif price_zone_change(symbol, 'ema44', 'ABOVE', latest_candles) \
    and (current_trend_bias == 'BULLISH'):
        return 'BUY'
    elif price_zone_change(symbol, 'ema78', 'ABOVE', latest_candles) \
    and (current_trend_bias == 'BULLISH'):
        return 'BUY'

    elif price_zone_change(symbol, 'ema13', 'BELOW', latest_candles) \
    and (current_trend_bias == 'BEARISH'):
        return 'SELL'
    elif price_zone_change(symbol, 'ema44', 'BELOW', latest_candles) \
    and (current_trend_bias == 'BEARISH'):
        return 'SELL'
    elif price_zone_change(symbol, 'ema78', 'BELOW', latest_candles) \
    and (current_trend_bias == 'BEARISH'):
        return 'SELL'

    else:
        return 'WAIT'

# 1) connect to local MT5 instance running on macOS.
# using python keyring to securely store credentials,
# then continue with other initialisation prepwork.
# terminal path override is needed to work vs the default using \\
windows_terminal_path = 'C:/Program Files/MetaTrader 5/terminal64.exe'
mt5.initialize(path=windows_terminal_path)
mt5_login = int(keyring.get_password('MT5_Account', 'login'))
mt5_password = keyring.get_password('MT5_Account', 'password')
mt5_server = keyring.get_password('MT5_Account', 'server')
mt5.login(mt5_login, mt5_password, mt5_server)

# initial clear screen before printing figures
# and reduce terminal window size if enabled
os.system('cls' if os.name == 'nt' else 'clear')
# optimally reduce terminal size to show status
if resize_terminal_window:
    terminal_rows = 5
    if display_max_balance:
        terminal_rows += 1
    if display_balance:
        terminal_rows += 1
    if display_equity:
        terminal_rows += 1
    if display_trend_bias:
        terminal_rows += 1
    original_term_size = os.get_terminal_size()
    sys.stdout.write(f'\x1b[8;{terminal_rows};{25}t')
    sys.stdout.flush()

# below accept key inputs without enter
# and restore original setting on exit
def restore_terminal():
    termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_terminal_settings)
stdin_fd = sys.stdin.fileno()
old_terminal_settings = termios.tcgetattr(stdin_fd)
atexit.register(restore_terminal)
tty.setcbreak(stdin_fd)

# below start command to not let laptop sleep
# but allow display dim while still running
subprocess.Popen(
    ['caffeinate', '-i', '-w', str(os.getpid())],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

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

# start equity curve background process before entering loop
if display_equity_curve:
    subprocess.Popen(
        [sys.executable, 'equity_curve.py'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

# initialise EMAs calculation engine before entering loop
ema_engine = FastEMAEngine(default_trade_symbol,
    trend_bias_timeframes[selected_trade_timeframe][1],
    tf_seconds=trend_bias_timeframes[selected_trade_timeframe][2])
last_emas_checked_bucket = -1

# 3) risk engine loop based on polling_period_in_sec
try:
    while True:
        # get latest account figures at every cycle
        account = mt5.account_info()

        # 4) only print periodically to reduce cpu usage
        # if enabled, log intraday equity periodically
        current_time = time.monotonic()
        if ((current_time - last_printout_time) >= 30) or force_subloop_refresh:
            # update counter for next loop cycle
            last_printout_time = current_time
            # reset force refresh of this subloop
            force_subloop_refresh = False
            # print risk notice once per print cycle
            risk_exceeded_printed = False

            # 5) update daily peak balance and store it
            # then calculate daily and weekly risk floors
            # do this within 30-sec loop to save CPU and I/O
            if (account.balance + capital_park_in_bank) > daily_peak_balance:
                daily_peak_balance = account.balance + capital_park_in_bank
                if daily_peak_balance > weekly_peak_balance:
                    weekly_peak_balance = daily_peak_balance
                with open(risk_data_file, 'w') as f:
                    f.write(f'{current_date},{daily_peak_balance:.2f},'
                        f'{weekly_peak_balance:.2f},{capital_park_in_bank:.2f}')

            # risk floor calculation can skip main loop and do every 30 seconds
            # possible that within 30 seconds a big move happened and reversed
            # but that would be caught by the trade risk and different stops
            # without the new daily risk floor being used for this edge case
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
                    elapsed_trading_hours = 0 # handle session starting earlier
                limit_percentage = (elapsed_trading_hours + trading_hours_per_session) \
                                   // trading_hours_per_session / total_trading_sessions
                limit_percentage = min(limit_percentage, 1.0) # handle session ending later
                daily_risk_floor = (1 - limit_percentage * daily_risk_percentage) \
                                   * daily_peak_balance
                weekly_risk_floor = (1 - weekly_risk_percentage) * weekly_peak_balance

            # calculate and display trade size for next trade
            # accounting for remaining daily risk for next trade
            # calculate even when not displaying to place trades
            available_risk_capital = (account.equity + capital_park_in_bank) - \
                                        max(daily_risk_floor, weekly_risk_floor)
            trade_risk_capital = trade_risk_percentage * daily_peak_balance
            next_trade_size = trade_size_constant * (account.equity + capital_park_in_bank)
            if available_risk_capital <= 0:
                next_trade_size = 0
            elif available_risk_capital < trade_risk_capital:
                next_trade_size = next_trade_size * available_risk_capital / trade_risk_capital
            if default_trade_symbol != 'USTEC':
                next_trade_size = float(Decimal(str(next_trade_size)).quantize(Decimal('0.01')))
            else:
                next_trade_size = float(Decimal(str(next_trade_size)).quantize(Decimal('0.1')))
            if display_trade_size:
                trade_size_text = '\nSize:    ' + f'{Decimal(f'{next_trade_size:.2g}'):f}'
            else:
                trade_size_text = ''

            if not swing_trading_mode:
                trade_symbol_text = default_trade_symbol
            else:
                trade_symbol_text = 'SWING'
                # calculate remaining risk budget factoring all stop losses
                # formula would be balance - stop losses - weekly_risk_floor
                # fair assumption is that all positions have stop losses set
                total_stop_losses = 0
                positions = mt5.positions_get()
                if positions is None or len(positions) == 0:
                    pass
                else:
                    for pos in positions:
                        # need to address this edge case of no stop loss
                        # value will be wrong but better than no value
                        if pos.sl == 0:
                            pass
                        else:
                            position_stop_loss = abs(pos.price_open - pos.sl) * pos.volume
                            # special handling for forex symbols because 1 lot = 100000
                            # check for major forex pairs with USD, can add minors later
                            if pos.symbol in FOREX_PAIRS:
                                position_stop_loss *= 100000
                            total_stop_losses += position_stop_loss
                risk_budget_left = account.balance + capital_park_in_bank \
                                   - total_stop_losses - weekly_risk_floor
                trade_size_text = '\nBudget:  ' + f'{risk_budget_left:.2f}'

            # 6) calculate EMAs for use in trend classification
            tick = mt5.symbol_info_tick(default_trade_symbol)
            current_emas_bucket = int(tick.time) // \
                trend_bias_timeframes[selected_trade_timeframe][2]
            if current_emas_bucket != last_emas_checked_bucket:
                ema_data = ema_engine.update(tick.bid)
                last_emas_checked_bucket = current_emas_bucket
            else:
                ema_data = ema_engine.fast_live_only(tick.bid)

            if display_trend_bias:
                current_trend_bias = get_current_trend(default_trade_symbol)
                trend_bias_text = '\nBias:    ' + current_trend_bias + '\n'
                # + ' ' + f'{ema_data['ema44']:.2f}' + ' ' + f'{ema_data['ema78']:.2f}' + '\n'
            else:
                trend_bias_text = '\n'
            if display_max_balance:
                max_balance_text = '\nMaximum: ' + f'{daily_peak_balance:.2f}'
            else:
                max_balance_text = ''
            if display_balance:
                balance_text = '\nCurrent: ' + f'{account.balance + capital_park_in_bank:.2f}'
            else:
                balance_text = ''
            if display_equity:
                equity_text = '\nEquity:  ' + f'{account.equity + capital_park_in_bank:.2f}' 
            else:
                equity_text = ''
            pnl_text = '\nP&L:     ' + f'{account.profit:.2f}'
            
            # use special code to clear screen not slower OS I/O
            print('\033[H\033[J[Risk 13 x ' + trade_symbol_text + ']', \
                max_balance_text, balance_text, equity_text, pnl_text, \
                trade_size_text, trend_bias_text, force_refresh_msg)
            force_refresh_msg = ''

            if log_intraday_equity:
                with open('equity_curve.txt', mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), 
                        round(account.equity + capital_park_in_bank, 2)
                    ])

        # 7) check if trades exceeded trades risk limit
        # then flatten all open positions to force close
        # this effectively acts as stop loss at trade limit
        for trade_symbol in watchlist_symbols:
            positions = mt5.positions_get(trade_symbol[0])
            if positions is None or len(positions) == 0:
                pass
            else:
                symbol_total_profit = 0
                for pos in positions:
                   symbol_total_profit += pos.profit
                if symbol_total_profit < (-trade_risk_percentage * \
                cut_loss_multiplier * daily_peak_balance):
                    flatten_all_positions(trade_symbol[0])
                    print('[TRADE RISK EXCEEDED]')

        # 8) check if equity exceeded daily risk limit
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

        # 9) breakeven and protective stops to limit loss and protect profit
        trade_risk_amount = trade_risk_percentage * daily_peak_balance
        for index, trade_symbol in enumerate(watchlist_symbols): 
            positions = mt5.positions_get(trade_symbol[0])
            if positions is None or len(positions) == 0:
                trade_peak_profit[index] = 0
            else:
                symbol_total_profit = 0
                for pos in positions:
                   symbol_total_profit += pos.profit
                if symbol_total_profit > trade_peak_profit[index]:
                    trade_peak_profit[index] = symbol_total_profit
                positions_already_flattened = False

                if breakeven_stop and (symbol_total_profit <= 0) and \
                (trade_peak_profit[index] >= (breakeven_setting * trade_risk_amount)):
                    flatten_all_positions(trade_symbol[0])
                    positions_already_flattened = True
                    print('[BREAKEVEN TRIGGERED]')

                if profit_stop and not positions_already_flattened:
                    for threshold in profit_setting:
                        if (trade_peak_profit[index] >= (threshold * trade_risk_amount)) \
                        and (symbol_total_profit \
                        <= (profit_stop_percentage * threshold * trade_risk_amount)):
                            flatten_all_positions(trade_symbol[0])
                            positions_already_flattened = True
                            print(f'[{threshold}R STOP TRIGGERED]')
                            break

                if protective_stop and not positions_already_flattened:
                    for threshold in protective_setting:
                        if (trade_peak_profit[index] >= (threshold[0] * trade_risk_amount)) \
                        and (symbol_total_profit \
                        <= (trade_peak_profit[index] - (threshold[1] * trade_risk_amount))):
                            flatten_all_positions(trade_symbol[0])
                            print(f'[{threshold[0]}R STOP TRIGGERED]')
                            break

        # 10) handle trade entry detection and followup actions
        if enable_auto_trade_entry_testing:
            tick = mt5.symbol_info_tick(default_trade_symbol)
            current_entry_bucket = int(tick.time) // \
                trend_bias_timeframes[selected_trade_timeframe][2]
            if current_entry_bucket != last_entry_checked_bucket:
                last_entry_checked_bucket = current_entry_bucket
                positions = mt5.positions_get(default_trade_symbol)
                if positions is None or len(positions) == 0:
                    # if no position when state has position means position closed
                    # thus collect P&L data for auto-trading heuristics input
                    # mt5-mac package has history function but don't work
                    if trade_position_open[selected_trade_symbol]:
                        account = mt5.account_info() # position might cut from call above
                        trade_position_open[selected_trade_symbol] = False
                        account_balance_history[selected_trade_symbol].append(account.balance)

                    # now run signal check, sanity checks, execution and logging
                    trade_entry_signal = ema_rejection_setup(default_trade_symbol)
                    if trade_entry_signal != 'WAIT':
                        # heuristics-based switching by checking if algo mismatches market state
                        if auto_trade_heuristics_switch:
                            # build heuristics logic here
                            if True:
                                auto_trade_reverse_signals = not auto_trade_reverse_signals
                        # handle trading reverse of signal because algo mismatches market state
                        if auto_trade_reverse_signals:
                            if trade_entry_signal == 'BUY':
                                signal_to_execute = 'SELL'
                            elif trade_entry_signal == 'SELL':
                                signal_to_execute = 'BUY'
                        else:
                            signal_to_execute = trade_entry_signal
                        # avoid placing trades where exchanges and symbols are closed
                        # in this case, avoid 2000 to 0000 UTC reasonable window
                        # even if accounting for daylight savings changes
                        if enable_auto_trade_place_trades and \
                        datetime.now(timezone.utc).hour < 20:
                            # sanity check on distributed daily risk limit
                            # or weekly risk limit whichever is higher
                            if weekly_risk_floor > daily_risk_floor:
                                current_risk_floor = weekly_risk_floor
                            else:
                                current_risk_floor = daily_risk_floor
                            # basic check on account balance if 2x of stop loss inc margin
                            # don't factor cut_loss_multiplier to get more conservative value
                            # use min amount fallback in account to prevent denial of service
                            # also use equity value to factor in other symbols losing positions
                            if ((account.equity + capital_park_in_bank) > current_risk_floor) and \
                            (account.equity > (2 * trade_risk_percentage * daily_peak_balance)) \
                            and (account.equity > account_autotrade_minimum_balance):
                                lot_size = next_trade_size
                                open_new_trade(default_trade_symbol, signal_to_execute, \
                                    lot_size, sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                                print('[' + signal_to_execute + ' ORDER SENT]')
                                trade_position_open[selected_trade_symbol] = True
                        with open('entry_signals.txt', mode='a', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow([(datetime.now(timezone.utc) + \
                            timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
                            trade_entry_signal,signal_to_execute])

        # 11) handle pre-defined keys to place or close trades
        # will wait up to polling_period_in_sec delay but
        # immediately execute on keypress detected 
        if enable_keys_to_trade:
            key_ready, _, _ = select.select([sys.stdin], [], [], polling_period_in_sec)
            if key_ready:
                key_pressed = sys.stdin.read(1).lower()
                lot_size = next_trade_size 

                if key_pressed == 'x':
                    flatten_all_positions()
                    print('[CLOSE ORDER SENT]')
                elif key_pressed == 'n':
                    flatten_all_positions(default_trade_symbol)
                    print('[CLOSE ORDER SENT]')
                elif key_pressed == 'j':
                    positions = mt5.positions_get(default_trade_symbol)
                    if positions is None or len(positions) == 0:
                        print('[NOTHING TO FLIP]')
                    elif block_countertrend_trades:
                        tick = mt5.symbol_info_tick(default_trade_symbol)
                        ema_data = ema_engine.fast_live_only(tick.bid)
                        current_trend_bias = get_current_trend(default_trade_symbol)
                        if positions[0].type == mt5.POSITION_TYPE_BUY:
                            trade_direction = 'SELL'
                        else:
                            trade_direction = 'BUY'
                        if (trade_direction == 'BUY' and current_trend_bias == 'BULLISH') or \
                            (trade_direction == 'SELL' and current_trend_bias == 'BEARISH'):
                            flatten_all_positions(default_trade_symbol)
                            # reset or new position can close right away
                            trade_peak_profit[selected_trade_symbol] = 0
                            open_new_trade(default_trade_symbol, trade_direction, lot_size, \
                                sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                            print('[FLIP ORDER SENT]') 
                        else:
                            print('[FLIP AGAINST BIAS]')
                    else:
                        flatten_all_positions(default_trade_symbol)
                        # reset or new position can close right away
                        trade_peak_profit[selected_trade_symbol] = 0
                        if positions[0].type == mt5.POSITION_TYPE_BUY:
                            trade_direction = 'SELL'
                        else:
                            trade_direction = 'BUY'
                        open_new_trade(default_trade_symbol, trade_direction, lot_size, \
                            sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                        print('[FLIP ORDER SENT]')
                elif key_pressed == 'h':
                    positions = mt5.positions_get(default_trade_symbol)
                    if positions is None or len(positions) == 0:
                        pass
                    else:
                        least_profitable_profit = None
                        least_profitable_position = None
                        for pos in positions:
                            if least_profitable_position is None:
                                least_profitable_profit = pos.profit
                                least_profitable_position = pos
                            elif pos.profit < least_profitable_profit:
                                least_profitable_profit = pos.profit
                                least_profitable_position = pos
                        if least_profitable_position.type == mt5.POSITION_TYPE_BUY:
                            trade_type = mt5.ORDER_TYPE_SELL
                            price = mt5.symbol_info_tick(least_profitable_position.symbol).bid
                        else:
                            trade_type = mt5.ORDER_TYPE_BUY
                            price = mt5.symbol_info_tick(least_profitable_position.symbol).ask
                        close_payload = {
                            'action': mt5.TRADE_ACTION_DEAL,
                            'symbol': least_profitable_position.symbol,
                            'volume': least_profitable_position.volume,
                            'type': trade_type,
                            'position': least_profitable_position.ticket,
                            'price': price,
                            'deviation': 30,
                            'magic': 999999,
                            'type_time': mt5.ORDER_TIME_GTC,
                            'type_filling': mt5.ORDER_FILLING_IOC,
                        }
                        result = mt5.order_send(close_payload)
                    print('[UNWIND ORDER SENT]')
                elif key_pressed == 'b':
                    positions = mt5.positions_get(default_trade_symbol)
                    if disable_adding_trades and not (positions is None or len(positions) == 0):
                        print('[NO ADDING TRADES]')
                    elif block_countertrend_trades:
                        tick = mt5.symbol_info_tick(default_trade_symbol)
                        ema_data = ema_engine.fast_live_only(tick.bid)
                        if get_current_trend(default_trade_symbol) == 'BULLISH':
                            open_new_trade(default_trade_symbol, 'BUY', lot_size, \
                                sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                            print('[BUY ORDER SENT]')
                        else:
                            print('[BIAS NOT BULLISH]')
                    else:
                        open_new_trade(default_trade_symbol, 'BUY', lot_size, \
                            sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                        print('[BUY ORDER SENT]')
                elif key_pressed == 'm':
                    positions = mt5.positions_get(default_trade_symbol)
                    if disable_adding_trades and not (positions is None or len(positions) == 0):
                        print('[NO ADDING TRADES]')
                    elif block_countertrend_trades:
                        tick = mt5.symbol_info_tick(default_trade_symbol)
                        ema_data = ema_engine.fast_live_only(tick.bid)
                        if get_current_trend(default_trade_symbol) == 'BEARISH':
                            open_new_trade(default_trade_symbol, 'SELL', lot_size, \
                                sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                            print('[SELL ORDER SENT]')
                        else:
                            print('[BIAS NOT BEARISH]')
                    else:   
                        open_new_trade(default_trade_symbol, 'SELL', lot_size, \
                            sl_pips=default_stop_loss_pips * cut_loss_multiplier)
                        print('[SELL ORDER SENT]')
                elif key_pressed.isdigit():
                    if len(watchlist_symbols) > int(key_pressed):
                        selected_trade_symbol = int(key_pressed)
                        default_trade_symbol = watchlist_symbols[selected_trade_symbol][0]
                        trade_size_constant = watchlist_symbols[selected_trade_symbol][1]
                        default_stop_loss_pips = watchlist_symbols[selected_trade_symbol][2]
                        if micro_trading_enabled:
                            trade_size_constant /= 10
                        elif light_trading_enabled:
                            trade_size_constant /= 2
                        # only need force refresh at this branch because trade size calculation
                        # is done in the subloop and needs to recalculate base on new symbol
                        force_refresh_msg = '\n[' + default_trade_symbol + ' SELECTED]'
                        force_subloop_refresh = True
                    else:
                        print('[SYMBOL UNDEFINED]')
                elif key_pressed == ',':
                    cut_loss_multiplier = 0.25
                    print('[25% CUTLOSS SET]')
                elif key_pressed == '.':
                    cut_loss_multiplier = 0.50
                    print('[50% CUTLOSS SET]')
                elif key_pressed == '/':
                    cut_loss_multiplier = 1.00
                    print('[100% CUTLOSS SET]')
                elif key_pressed == 'k':
                    if protective_stop or profit_stop:
                        protective_stop = False
                        profit_stop = False
                        print('[TRAILING STOPS OFF]')
                    else:
                        protective_stop = True
                        profit_stop = True
                        print('[TRAILING STOPS ON]')

        else: 
            # delay anyway avoid useless computation cycles
            time.sleep(polling_period_in_sec)

except KeyboardInterrupt:
    # graceful exit for Control+C to kill risk engine process
    pass

finally:
    # 12) terminate engine process by sending shutdown to MT5
    # clear screen and resize back terminal window if needed
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()
    if resize_terminal_window:
        sys.stdout.write(f'\x1b[8;{original_term_size.lines};{original_term_size.columns}t')
        sys.stdout.flush()        
    mt5.shutdown()

