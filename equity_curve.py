import os
import time
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mtick

# Stops Matplotlib from forcing the window to the front upon every visual draw.
plt.rcParams["figure.raise_window"] = False

def stream_live_equity_dashboard(csv_path="equity_curve.txt", timeout_minutes=1):
    plt.ion()
    fig, (ax1, ax2) = plt.subplots(
        2, 1, 
        figsize=(10, 6), 
        sharex=True, 
        gridspec_kw={'height_ratios': [3, 1]},
        num="Equity Curve"
    )
    plt.style.use('seaborn-v0_8-darkgrid' if 'seaborn-v0_8-darkgrid' in plt.style.available else 'default')

    timestamps = []
    equity_percentages = []
    drawdown_percentages = []
    
    initial_equity = None
    peak_equity_pct = 100.0

    consecutive_empty_checks = 0
    max_empty_checks = (timeout_minutes * 60) // 30 

    while not os.path.exists(csv_path):
        time.sleep(30)

    with open(csv_path, 'r') as f:
        running = True
        while running:
            new_lines_found = False
            while True:
                line = f.readline()
                if not line:
                    break  
                
                try:
                    ts_str, eq_str = line.strip().split(',')
                    ts = pd.to_datetime(ts_str)
                    eq = float(eq_str)
                    
                    if initial_equity is None:
                        initial_equity = eq
                        
                    eq_pct = (eq / initial_equity) * 100.0
                    
                    if not equity_percentages:
                        peak_equity_pct = eq_pct
                    else:
                        if eq_pct > peak_equity_pct:
                            peak_equity_pct = eq_pct
                            
                    dd_pct = peak_equity_pct - eq_pct
                    
                    timestamps.append(mdates.date2num(ts))
                    equity_percentages.append(eq_pct)
                    drawdown_percentages.append(dd_pct)
                    new_lines_found = True

                except (ValueError, ZeroDivisionError):
                    continue

            if new_lines_found:
                consecutive_empty_checks = 0
                
                if len(timestamps) > 1:
                    ax1.clear()
                    ax2.clear()
                    
                    ax1.plot(timestamps, equity_percentages, color='#007aff', linewidth=2)
                    ax2.fill_between(timestamps, 0, [-d for d in drawdown_percentages], color='#ff3b30', alpha=0.3)
                    ax2.plot(timestamps, [-d for d in drawdown_percentages], color='#ff3b30', linewidth=1)
                    
                    ax1.set_title("", fontsize=12, fontweight='bold')
                    ax1.set_ylabel("Equity (%)")
                    ax2.set_ylabel("Drawdown (%)")
                    
                    ax1.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=2))
                    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=2))
                    
                    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
                    fig.autofmt_xdate()
                    
                    # Force background data re-rendering without changing desktop priority
                    fig.canvas.draw_idle()
            else:
                if len(timestamps) > 0:  
                    consecutive_empty_checks += 1
                    
            if consecutive_empty_checks >= max_empty_checks:
                plt.ioff()
                plt.savefig("equity_curve.png", dpi=150, bbox_inches='tight')
                running = False  
                break

            # Use below instead of plt.pause() which natively triggers windows to jump forward.
            # Flushes events and sleeps for 30 seconds directly inside background thread canvas.
            fig.canvas.flush_events()
            fig.canvas.start_event_loop(30)
            
    plt.close(fig) 

if __name__ == "__main__":
    stream_live_equity_dashboard()

