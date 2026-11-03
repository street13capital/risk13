import os
import time
from datetime import datetime, timezone
import keyring
import mt5_mac as mt5

# parameters for risk engine
trade_risk_percentage = 0.020
daily_risk_percentage = 0.067
weekly_risk_percentage = 0.20
polling_period_in_sec = 0.250
risk_data_file = 'risk_engine.txt'

daily_peak_balance = None
weekly_peak_balance = None
last_printout_time = 0

def flatten_all_positions():
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

def apply_stop_loss():
    # this function request just do not work after deep debugging
    # bug or limitation end-to-end, use other workaround for SL logic
    # retain code in this section for possible future use in other ways
    global trade_risk_percentage, daily_peak_balance

    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        return

    for pos in positions:
        if pos.sl == 0.0:
            ticket = pos.ticket
            symbol = pos.symbol
            position_type = pos.type
            open_price = pos.price_open

            # calculate cost per point for symbol
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                continue
            symbol_point = symbol_info.point
            contract_size = symbol_info.contract_size
            if contract_size == None or contract_size == 0.0:
                contract_size = symbol_info.margin_initial
                if contract_size == None or contract_size == 0.0:
                    contract_size = 100000.0
            cost_per_point = pos.volume * contract_size * symbol_point

            # distribute stop loss amount evenly to existing positions
            stop_loss_amount = trade_risk_percentage * daily_peak_balance / len(positions)

            # calculate stop loss points and offset from open price
            stop_loss_points = stop_loss_amount / cost_per_point * symbol_point
            if position_type == mt5.ORDER_TYPE_BUY:
                stop_loss = open_price - stop_loss_points
            elif position_type == mt5.ORDER_TYPE_SELL:
                stop_loss = open_price + stop_loss_points
            else:
                continue

            stoploss_payload = {
                'action': mt5.TRADE_ACTION_SLTP,
                'position': ticket,
                'symbol': symbol,
                'sl': round(stop_loss, symbol_info.digits),
                'tp': pos.tp
            }
            result = mt5.order_send(stoploss_payload)
  
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
current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
if os.path.exists(risk_data_file):
    with open(risk_data_file, 'r') as f:
        last_saved_date, last_saved_balance, saved_weekly_balance = f.read().strip().split(',')
        weekly_peak_balance = float(saved_weekly_balance)
        if last_saved_date == current_date:
            daily_peak_balance = float(last_saved_balance)
        else:
            # refresh daily peak balance on new day
            account = mt5.account_info()
            daily_peak_balance = account.balance
            # refresh weekly peak balance on new week
            if datetime.now(timezone.utc).weekday() == 0:
                weekly_peak_balance = daily_peak_balance
            with open(risk_data_file, 'w') as f:
                f.write(f'{current_date},{daily_peak_balance},{weekly_peak_balance}')
else:
    account = mt5.account_info()
    daily_peak_balance = account.balance
    weekly_peak_balance = daily_peak_balance
    with open(risk_data_file, 'w') as f:
        f.write(f'{current_date},{daily_peak_balance},{weekly_peak_balance}')

# 3) risk engine loop based on period polling_period_in_sec
try:
    while True:
        account = mt5.account_info()
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
            if daily_peak_balance > weekly_peak_balance:
                weekly_peak_balance = daily_peak_balance
            with open(risk_data_file, 'w') as f:
                f.write(f'{current_date},{daily_peak_balance},{weekly_peak_balance}')

        # 5) check if trades exceeded trades risk limit
        # then flatten all open positions to force close
        if (account.profit < (-trade_risk_percentage * daily_peak_balance)):
            flatten_all_positions()
            print('[TRADE RISK EXCEEDED]')

        # 6) check if balance exceeded daily risk limit
        # then flatten all open positions if there is any
        daily_risk_floor = (1 - daily_risk_percentage) * daily_peak_balance
        weekly_risk_floor = (1 - weekly_risk_percentage) * weekly_peak_balance
        if weekly_risk_floor > daily_risk_floor:
            if account.equity < weekly_risk_floor:
                flatten_all_positions()
                print('[WEEKLY RISK EXCEEDED]')
        elif account.equity < daily_risk_floor:
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
