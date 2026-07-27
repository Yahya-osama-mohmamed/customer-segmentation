"""Online Retail II: loading, cleaning, and RFM feature engineering.

The dataset is raw invoice lines (Dec 2009 - Dec 2011, two workbook sheets).
Every customer-level feature here is BUILT from those raw lines — nothing is
pre-aggregated.

Cleaning decisions (each counted and printed, never silent):
- Cancelled invoices (Invoice starting with 'C') removed — they are credit
  notes, not purchases.
- Non-positive Quantity or Price removed (returns, data errors, and manual
  adjustment rows such as bad-debt postings).
- Rows without a Customer ID removed — anonymous transactions cannot be
  segmented.
- Non-product stock codes (POST, DOT, M, BANK CHARGES, ...) removed so
  postage/fees don't inflate Monetary.
"""

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_ROOT / "data" / "raw" / "online_retail_II.xlsx"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# Service/administrative stock codes that are not products
NON_PRODUCT_CODES = {
    "POST", "DOT", "M", "S", "AMAZONFEE", "BANK CHARGES", "C2", "D",
    "CRUK", "ADJUST", "ADJUST2", "TEST001", "TEST002", "PADS", "B",
}


def load_raw(path: Path = RAW_FILE) -> pd.DataFrame:
    """Load and concatenate both workbook sheets (~1.07M rows)."""
    sheets = pd.read_excel(path, sheet_name=None, dtype={"Invoice": str,
                                                         "StockCode": str})
    df = pd.concat(sheets.values(), ignore_index=True)
    df.columns = [c.strip().replace(" ", "") for c in df.columns]  # CustomerID
    return df


def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the documented cleaning steps, printing what each one drops."""
    n0 = len(df)
    df = df.copy()

    cancelled = df["Invoice"].str.startswith("C", na=False)
    df = df[~cancelled]
    n1 = len(df)

    df = df[(df["Quantity"] > 0) & (df["Price"] > 0)]
    n2 = len(df)

    df = df.dropna(subset=["CustomerID"])
    n3 = len(df)

    df = df[~df["StockCode"].str.upper().isin(NON_PRODUCT_CODES)]
    n4 = len(df)

    df["CustomerID"] = df["CustomerID"].astype(int)
    df["Revenue"] = df["Quantity"] * df["Price"]
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])

    print(f"clean_transactions(): start {n0:,}")
    print(f"  - cancelled invoices:       -{n0 - n1:,}")
    print(f"  - non-positive qty/price:   -{n1 - n2:,}")
    print(f"  - missing CustomerID:       -{n2 - n3:,}")
    print(f"  - non-product stock codes:  -{n3 - n4:,}")
    print(f"  = kept {n4:,} rows ({n4 / n0:.1%})")
    return df.reset_index(drop=True)


def build_rfm(tx: pd.DataFrame, snapshot: pd.Timestamp | None = None) -> pd.DataFrame:
    """Customer-level RFM + behavioral features, as of `snapshot`.

    Beyond classic R/F/M:
    - AvgOrderValue      — Monetary / Frequency
    - InterPurchaseStd   — std dev of days between orders ("regular" vs
                           "sporadic" buyers); NaN for single-order customers
    - ProductDiversity   — distinct products purchased (StockCode count)
    - TenureDays         — days between first and last purchase
    """
    snapshot = snapshot or tx["InvoiceDate"].max() + pd.Timedelta(days=1)

    invoices = (tx.groupby(["CustomerID", "Invoice"])
                  .agg(inv_date=("InvoiceDate", "min"),
                       inv_revenue=("Revenue", "sum"))
                  .reset_index())

    def interpurchase_std(dates):
        if len(dates) < 3:
            return np.nan
        deltas = np.diff(np.sort(dates.values).astype("datetime64[D]")).astype(float)
        return float(np.std(deltas))

    per_customer = invoices.groupby("CustomerID").agg(
        Recency=("inv_date", lambda d: (snapshot - d.max()).days),
        Frequency=("Invoice", "nunique"),
        Monetary=("inv_revenue", "sum"),
        FirstPurchase=("inv_date", "min"),
        LastPurchase=("inv_date", "max"),
        InterPurchaseStd=("inv_date", interpurchase_std),
    )
    per_customer["AvgOrderValue"] = per_customer["Monetary"] / per_customer["Frequency"]
    per_customer["TenureDays"] = (
        per_customer["LastPurchase"] - per_customer["FirstPurchase"]).dt.days

    diversity = tx.groupby("CustomerID")["StockCode"].nunique().rename("ProductDiversity")
    country = (tx.groupby("CustomerID")["Country"]
                 .agg(lambda s: s.mode().iloc[0]).rename("Country"))

    rfm = per_customer.join(diversity).join(country).reset_index()
    print(f"build_rfm(): {len(rfm):,} customers | snapshot {snapshot.date()}")
    return rfm


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tx = clean_transactions(load_raw())
    tx.to_parquet(PROCESSED_DIR / "transactions_clean.parquet", index=False)
    rfm = build_rfm(tx)
    rfm.to_parquet(PROCESSED_DIR / "rfm_features.parquet", index=False)
    print("saved transactions_clean.parquet + rfm_features.parquet")


if __name__ == "__main__":
    main()
