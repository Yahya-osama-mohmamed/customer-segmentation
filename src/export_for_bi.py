"""Export flat, BI-ready tables for the Power BI dashboard.

Outputs (dashboard/data/):
- customers.csv     one row per customer: RFM, behavior features, segment
- transactions.csv  invoice-line level with segment joined in + calendar cols
                    (needed for the revenue-trend and product views)
- segment_summary.csv  the named segment profile table
"""

from pathlib import Path

import pandas as pd

from src.rfm import PROCESSED_DIR, PROJECT_ROOT

BI_DIR = PROJECT_ROOT / "dashboard" / "data"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def main() -> None:
    BI_DIR.mkdir(parents=True, exist_ok=True)

    customers = pd.read_parquet(PROCESSED_DIR / "customers_segmented.parquet")
    out_customers = customers[[
        "CustomerID", "Segment", "Recency", "Frequency", "Monetary",
        "AvgOrderValue", "InterPurchaseStd", "ProductDiversity",
        "TenureDays", "Country",
    ]].copy()
    out_customers["Monetary"] = out_customers["Monetary"].round(2)
    out_customers["AvgOrderValue"] = out_customers["AvgOrderValue"].round(2)
    out_customers["InterPurchaseStd"] = out_customers["InterPurchaseStd"].round(1)
    out_customers.to_csv(BI_DIR / "customers.csv", index=False)
    print(f"customers.csv: {out_customers.shape}")

    tx = pd.read_parquet(PROCESSED_DIR / "transactions_clean.parquet")
    seg_map = customers.set_index("CustomerID")["Segment"]
    tx["Segment"] = tx["CustomerID"].map(seg_map)
    tx["Revenue"] = tx["Revenue"].round(2)
    d = pd.to_datetime(tx["InvoiceDate"])
    tx["Date"] = d.dt.strftime("%Y-%m-%d")
    tx["Year"] = d.dt.year
    tx["MonthNum"] = d.dt.month
    tx["Month"] = d.dt.month.map(lambda m: MONTHS[m - 1])
    tx["YearMonth"] = d.dt.strftime("%Y-%m")
    out_tx = tx[["Invoice", "Date", "Year", "MonthNum", "Month", "YearMonth",
                 "CustomerID", "Segment", "Country", "StockCode", "Description",
                 "Quantity", "Price", "Revenue"]]
    out_tx.to_csv(BI_DIR / "transactions.csv", index=False)
    print(f"transactions.csv: {out_tx.shape}")

    prof = pd.read_csv(PROCESSED_DIR / "segment_profile.csv")
    prof.to_csv(BI_DIR / "segment_summary.csv", index=False)
    print(f"segment_summary.csv: {prof.shape}")


if __name__ == "__main__":
    main()
