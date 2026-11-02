import keyring
import mt5_mac as mt5
windows_terminal_path = "C:/Program Files/MetaTrader 5/terminal64.exe"

mt5.initialize(path=windows_terminal_path)
mt5_login = int(keyring.get_password('MT5_Account', 'login'))
mt5_password = keyring.get_password('MT5_Account', 'password')
mt5_server = keyring.get_password('MT5_Account', 'server')
mt5.login(mt5_login, mt5_password, mt5_server)

account = mt5.account_info()
print(account.balance, account.equity, account.profit)

mt5.shutdown()
