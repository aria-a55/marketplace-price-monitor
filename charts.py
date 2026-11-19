from datetime import datetime, timedelta
from io import BytesIO

import matplotlib.dates as mdates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from price_finder import format_price


def build_price_chart(history, threshold_kop=None):
    """Строит PNG по сохранённым датам и ценам в копейках."""
    dates = [datetime.fromisoformat(row["checked_at"]) for row in history]
    prices = [row["price_kop"] / 100 for row in history]

    figure = Figure(figsize=(9, 4.5), layout="constrained")
    canvas = FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.plot(dates, prices, color="#1565c0", linewidth=2, marker="o",
              markersize=4 if len(prices) <= 50 else 0, label="Цена")
    if threshold_kop is not None:
        axes.axhline(threshold_kop / 100, color="#b44d18", linestyle="--",
                     label=f"Порог: {format_price(threshold_kop)}")
        axes.legend()

    locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
    axes.xaxis.set_major_locator(locator)
    axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    if dates[0] == dates[-1]:
        margin = timedelta(hours=1)
        axes.set_xlim(dates[0] - margin, dates[0] + margin)
    axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}".replace(".", ",")))
    axes.set_title("История цен")
    axes.set_xlabel("Дата и время проверки")
    axes.set_ylabel("Цена, ₽")
    axes.grid(alpha=0.25)

    output = BytesIO()
    output.name = "price-history.png"
    canvas.print_png(output)
    output.seek(0)
    return output
