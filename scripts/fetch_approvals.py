#!/usr/bin/env python3
"""
Fetches LAC approvals from Snowflake and writes them as masked JSON.

Output: data/approvals.json + data/last_updated.json
Runs hourly via GitHub Actions.

PII masking: mobile numbers shown as 98XXXX5660 format.
Customer names dropped entirely.
"""

import os
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import snowflake.connector

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
OUTPUT_DIR  = Path("data")
DATA_FILE   = OUTPUT_DIR / "approvals.json"
META_FILE   = OUTPUT_DIR / "last_updated.json"

# Pull last 30 days of approvals (filtering happens in the UI)
LOOKBACK_DAYS = 30

# India Standard Time (UTC+5:30) for display
IST = timezone(timedelta(hours=5, minutes=30))


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------
def mask_mobile(mobile: str) -> str:
    """98XXXX5660 format. Returns empty for invalid inputs."""
    if not mobile or not isinstance(mobile, str):
        return ""
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if len(digits) < 10:
        return ""
    last10 = digits[-10:]
    return f"{last10[:2]}XXXX{last10[6:]}"


def get_snowflake_connection():
    """Connect to Snowflake using GitHub Action secrets."""
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        role=os.environ.get("SNOWFLAKE_ROLE", "PUBLIC"),
        database="CFSPL_NBFC_DB",
    )


def fetch_approvals(conn):
    """Pull last 30 days of LAC approvals."""
    sql = f"""
    SELECT DISTINCT
      B.ID                                            AS rul_lead_id,
      A.CUSTOMER_DETAILS:contactNumber::STRING        AS mobile,
      TO_VARCHAR(B.CREATED_AT, 'YYYY-MM-DD HH24:MI')  AS approval_datetime,
      TO_VARCHAR(B.CREATED_AT, 'YYYY-MM-DD')          AS approval_date,
      A.STATE                                         AS funnel_state,
      B.SOURCE                                        AS source,
      B.SUB_SOURCE                                    AS sub_source,
      TO_VARCHAR(A.CREATED_AT, 'YYYY-MM-DD')          AS lead_created_date
    FROM CFSPL_NBFC_DB.PROD_MONGO_CENTRAL_LEADS_DB_PROD.PRE_STAMPED_LEADS A
    INNER JOIN CFSPL_NBFC_DB.PROD_CUSTOMER_FIN_LEAD_DB.LEAD_DETAILS B 
      ON A.LEAD_XID = B.PARENT_ID 
     AND B.ID ILIKE 'RUL%'
    LEFT JOIN CFSPL_NBFC_DB.PROD_CUSTOMER_FIN_LEAD_DB.REJECTIONS C 
      ON B.ID = C.LEAD_ID
    WHERE TO_DATE(B.CREATED_AT) >= DATEADD('day', -{LOOKBACK_DAYS}, CURRENT_DATE())
      AND A.CHANNEL = 'LAC'
      AND A.STATUS <> 'EXPIRED'
      AND A.STATE <> 'INIT'
      AND C.REJECTION_REASONS IS NULL
    ORDER BY B.CREATED_AT DESC
    """

    cur = conn.cursor(snowflake.connector.DictCursor)
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()

    # Mask PII before serialization
    output = []
    for row in rows:
        output.append({
            "rul_lead_id":       row.get("RUL_LEAD_ID"),
            "mobile_masked":     mask_mobile(row.get("MOBILE")),
            "approval_datetime": row.get("APPROVAL_DATETIME"),
            "approval_date":     row.get("APPROVAL_DATE"),
            "funnel_state":      row.get("FUNNEL_STATE"),
            "source":            row.get("SOURCE") or "",
            "sub_source":        row.get("SUB_SOURCE") or "",
            "lead_created_date": row.get("LEAD_CREATED_DATE"),
        })
    return output


def main():
    print(f"[{datetime.now(IST).isoformat()}] Starting refresh...")

    try:
        conn = get_snowflake_connection()
    except Exception as e:
        print(f"FATAL: Could not connect to Snowflake: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        approvals = fetch_approvals(conn)
        print(f"Fetched {len(approvals)} approvals from Snowflake.")
    finally:
        conn.close()

    OUTPUT_DIR.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(approvals, indent=2))

    meta = {
        "last_updated_utc":  datetime.now(timezone.utc).isoformat(),
        "last_updated_ist":  datetime.now(IST).strftime("%d-%b-%Y %H:%M IST"),
        "row_count":         len(approvals),
        "lookback_days":     LOOKBACK_DAYS,
    }
    META_FILE.write_text(json.dumps(meta, indent=2))

    print(f"Wrote {DATA_FILE} ({len(approvals)} rows) and {META_FILE}.")


if __name__ == "__main__":
    main()
