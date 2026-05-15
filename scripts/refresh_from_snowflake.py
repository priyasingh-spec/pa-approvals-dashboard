import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import snowflake.connector


QUERY = """
SELECT DISTINCT 
  B.ID AS rul_lead_id,

  CASE
    WHEN CUSTOMER_DETAILS:contactNumber::STRING IS NULL THEN NULL
    WHEN LENGTH(CUSTOMER_DETAILS:contactNumber::STRING) >= 10 THEN
      CONCAT(
        LEFT(CUSTOMER_DETAILS:contactNumber::STRING, 2),
        'XXXX',
        RIGHT(CUSTOMER_DETAILS:contactNumber::STRING, 4)
      )
    ELSE CUSTOMER_DETAILS:contactNumber::STRING
  END AS mobile_masked,

  TO_CHAR(CONVERT_TIMEZONE('Asia/Kolkata', B.CREATED_AT), 'YYYY-MM-DD HH24:MI') AS approval_datetime,
  TO_CHAR(CONVERT_TIMEZONE('Asia/Kolkata', B.CREATED_AT), 'YYYY-MM-DD') AS approval_date,

  A.STATE AS funnel_state,
  'LAC' AS source,
  'PreStamped' AS sub_source,

  TO_CHAR(CONVERT_TIMEZONE('Asia/Kolkata', A.CREATED_AT), 'YYYY-MM-DD') AS lead_created_date

FROM CFSPL_NBFC_DB.PROD_MONGO_CENTRAL_LEADS_DB_PROD.PRE_STAMPED_LEADS A

LEFT JOIN CFSPL_NBFC_DB.PROD_CUSTOMER_FIN_LEAD_DB.LEAD_DETAILS B 
  ON A.LEAD_XID = B.PARENT_ID
  AND B.ID ILIKE 'RUL%'

LEFT JOIN CFSPL_NBFC_DB.PROD_CUSTOMER_FIN_LEAD_DB.REJECTIONS C 
  ON B.ID = C.LEAD_ID
  AND C.LEAD_ID ILIKE 'RUL%'

WHERE TO_DATE(A.CREATED_AT) >= '2026-05-13'
  AND A.CHANNEL = 'LAC'
  AND A.STATUS <> 'EXPIRED'
  AND A.STATE <> 'INIT'
  AND B.ID IS NOT NULL
  AND C.REJECTION_REASONS IS NULL

ORDER BY approval_datetime DESC;
"""


def main():
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        role=os.environ.get("SNOWFLAKE_ROLE") or None,
    )

    df = pd.read_sql(QUERY, conn)
    conn.close()

    df.columns = [col.lower() for col in df.columns]

    os.makedirs("data", exist_ok=True)

    with open("data/approvals.json", "w", encoding="utf-8") as f:
        json.dump(
            df.fillna("").to_dict(orient="records"),
            f,
            ensure_ascii=False,
            indent=2,
        )

    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    meta = {
        "last_updated_utc": now_utc,
        "last_updated_ist": now_ist.strftime("%d-%b-%Y %H:%M IST"),
        "row_count": int(len(df)),
        "source": "Snowflake",
    }

    with open("data/last_updated.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
