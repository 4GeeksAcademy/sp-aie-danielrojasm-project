"""
Safe snippet for basic pandas cleaning. Copy and adapt for your dataset.
Run: python pandas_clean.py  (ensure pandas is installed)
"""
import sys

import pandas as pd

# Load (adjust path and kwargs as needed)
SOURCE_PATH = "data.csv"
try:
    df = pd.read_csv(SOURCE_PATH)  # or read_json, read_excel
except FileNotFoundError:
    print(f"Error: file not found: {SOURCE_PATH}", file=sys.stderr)
    sys.exit(1)
except pd.errors.EmptyDataError:
    print(f"Error: {SOURCE_PATH} is empty or has no header row", file=sys.stderr)
    sys.exit(1)
except (pd.errors.ParserError, UnicodeDecodeError):
    print(f"Error: {SOURCE_PATH} is not a readable CSV file", file=sys.stderr)
    sys.exit(1)
except OSError as error:
    print(f"Error: could not read {SOURCE_PATH} ({error.strerror})", file=sys.stderr)
    sys.exit(1)

if df.empty:
    print(f"Error: {SOURCE_PATH} has a header but no rows to clean", file=sys.stderr)
    sys.exit(1)
print("df_shape", df.shape)
print("df_dtypes", df.dtypes)

# Drop fully null columns
df = df.dropna(axis=1, how="all")
print("df_shape_after_drop_all_null_cols", df.shape)

# Fill or drop nulls in key columns (customise columns)
# df = df.dropna(subset=["required_col"])
# df["optional_col"] = df["optional_col"].fillna(0)

# Normalise column names (optional)
df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
print("df_columns", list(df.columns))

# Deduplicate (optional)
before = len(df)
df = df.drop_duplicates()
print("rows_dropped_duplicates", before - len(df))

# Sample output
print("df_head", df.head())
