from collections import deque
import numpy as np
import mt5_mac as mt5

class FastEMAEngine:
    def __init__(self, symbol: str, timeframe, tf_seconds: int, lookback: int = 999):
        self.symbol = symbol
        self.tf = timeframe
        self.tf_seconds = tf_seconds
        self.lookback = lookback

        self.last_bar_time = 0
        self.ema13_closed = None
        self.ema44_closed = None
        self.ema78_closed = None

        # Stores the last 4 CLOSED candle 78-EMA values to compute a non-repainting 3-bar slope
        self.ema78_closed_hist = deque(maxlen=4)
        self.warmup()

    def _compute_series_with_tail(self, closes: np.ndarray, period: int, tail_len: int = 4):
        """Computes EMA series seeded by SMA and returns the final tail_len values."""
        alpha = 2.0 / (period + 1.0)
        ema = float(np.mean(closes[:period]))
        history = [ema] if len(closes) == period else []

        for price in closes[period:]:
            ema = alpha * float(price) + (1.0 - alpha) * ema
            history.append(ema)

        return history[-tail_len:]

    def warmup(self):
        """Loads full 999 bars from MT5 (used at startup and after any disconnect/sleep gap)."""
        bars = mt5.copy_rates_from_pos(self.symbol, self.tf, 0, self.lookback)
        if bars is None or len(bars) < 300:
            raise RuntimeError(f"Error loading {self.lookback} bars for {self.symbol}")

        # Ensure oldest-to-newest order (index 0 is timestamp, index 4 is close)
        if bars[0][0] > bars[-1][0]:
            bars = bars[::-1]

        # Exclude currently forming candle (bars[-1]) so closed EMAs are locked
        closed_closes = np.array([b[4] for b in bars[:-1]], dtype=np.float64)

        self.ema13_closed = self._compute_series_with_tail(closed_closes, 13, 1)[-1]
        self.ema44_closed = self._compute_series_with_tail(closed_closes, 44, 1)[-1]
        tail_78 = self._compute_series_with_tail(closed_closes, 78, 4)
        self.ema78_closed = tail_78[-1]
        self.ema78_closed_hist.clear()
        self.ema78_closed_hist.extend(tail_78)
        self.last_bar_time = int(bars[-1][0])

    def update(self, live_price: float) -> dict:
        """O(1) update on normal ticks. Full 999-bar reload if connection gap occurred."""
        latest = mt5.copy_rates_from_pos(self.symbol, self.tf, 0, 2)
        if latest is not None and len(latest) == 2:
            if latest[0][0] > latest[-1][0]:
                latest = latest[::-1]

            newest_time = int(latest[-1][0])
            time_diff = newest_time - self.last_bar_time
            if time_diff > self.tf_seconds:
                # Gap detected (laptop sleep, weekend, or MT5 disconnect) -> full reload
                self.warmup()
            elif time_diff == self.tf_seconds:
                # Normal single candle close -> roll prev_close into closed EMAs
                prev_close = float(latest[-2][4])
                self.ema13_closed = (2.0 / 14.0) * prev_close + (1.0 - 2.0 / 14.0) * self.ema13_closed
                self.ema44_closed = (2.0 / 45.0) * prev_close + (1.0 - 2.0 / 45.0) * self.ema44_closed
                self.ema78_closed = (2.0 / 79.0) * prev_close + (1.0 - 2.0 / 79.0) * self.ema78_closed
                self.ema78_closed_hist.append(self.ema78_closed)
                self.last_bar_time = newest_time

        # Live forming-candle EMAs (3 multiplications)
        ema13 = (2.0 / 14.0) * live_price + (1.0 - 2.0 / 14.0) * self.ema13_closed
        ema44 = (2.0 / 45.0) * live_price + (1.0 - 2.0 / 45.0) * self.ema44_closed
        ema78 = (2.0 / 79.0) * live_price + (1.0 - 2.0 / 79.0) * self.ema78_closed

        # Non-repainting 3-bar slope of 78 EMA (points per bar)
        slope78 = (
            (self.ema78_closed_hist[-1] - self.ema78_closed_hist[0]) / 3.0
            if len(self.ema78_closed_hist) == 4
            else 0.0
        )

        return {
            "ema13": ema13,
            "ema44": ema44,
            "ema78": ema78,
            "slope78": slope78,
        }

    def fast_live_only(self, live_price: float) -> dict:
        """Pure in-memory math (< 0.002 ms). Zero MT5 bridge calls."""
        ema13 = (2.0 / 14.0) * live_price + (1.0 - 2.0 / 14.0) * self.ema13_closed
        ema44 = (2.0 / 45.0) * live_price + (1.0 - 2.0 / 45.0) * self.ema44_closed
        ema78 = (2.0 / 79.0) * live_price + (1.0 - 2.0 / 79.0) * self.ema78_closed

        slope78 = (
            (self.ema78_closed_hist[-1] - self.ema78_closed_hist[0]) / 3.0
            if len(self.ema78_closed_hist) == 4
            else 0.0
        )

        return {
            "ema13": ema13,
            "ema44": ema44,
            "ema78": ema78,
            "slope78": slope78,
        }

    def update(self, live_price: float) -> dict:
        """Checks MT5 for a newly closed 5m candle (or gap), then returns live EMAs."""
        latest = mt5.copy_rates_from_pos(self.symbol, self.tf, 0, 2)
        if latest is not None and len(latest) == 2:
            if latest[0][0] > latest[-1][0]:
                latest = latest[::-1]

            newest_time = int(latest[-1][0])
            time_diff = newest_time - self.last_bar_time
            if time_diff > self.tf_seconds:
                self.warmup()  # Full 999-bar reload on gap/disconnect
            elif time_diff == self.tf_seconds:
                prev_close = float(latest[-2][4])
                self.ema13_closed = (2.0 / 14.0) * prev_close + (1.0 - 2.0 / 14.0) * self.ema13_closed
                self.ema44_closed = (2.0 / 45.0) * prev_close + (1.0 - 2.0 / 45.0) * self.ema44_closed
                self.ema78_closed = (2.0 / 79.0) * prev_close + (1.0 - 2.0 / 79.0) * self.ema78_closed
                self.ema78_closed_hist.append(self.ema78_closed)
                self.last_bar_time = newest_time

        return self.fast_live_only(live_price)

