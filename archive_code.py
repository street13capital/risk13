# archived functions here to keep risk engine script clean

def apply_stop_loss():
    # this function request just do not work after deep debugging
    # bug or limitation end-to-end, use other workaround for SL logic
    # retain code in this section for potential future use in other ways
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

