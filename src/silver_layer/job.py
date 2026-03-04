"""
Silver Layer Glue Job
Reads Bronze Parquet → Feature Engineering → Writes Silver Parquet

Features:
- Velocity windows (5m, 1h, 24h)
- User/merchant aggregates
- PII tokenization (SHA256 + salt)
- Merchant category enrichment
- Geographic distance calculations
"""

import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql import functions as F, Window
from pyspark.sql.types import *
from datetime import datetime, timedelta
import hashlib
import boto3

# Parse job arguments
args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'bronze_bucket',
    'silver_bucket',
    'environment',
    'pii_salt_secret'
])

# Initialize Spark
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

print(f"[Silver Job] Starting: {args['JOB_NAME']}")
print(f"[Silver Job] Bronze bucket: {args['bronze_bucket']}")
print(f"[Silver Job] Silver bucket: {args['silver_bucket']}")


# ==================== PII Tokenization ====================

def get_pii_salt():
    """Get PII hashing salt from Secrets Manager."""
    secrets_client = boto3.client('secretsmanager')
    response = secrets_client.get_secret_value(SecretId=args['pii_salt_secret'])
    return response['SecretString']


pii_salt = get_pii_salt()


def hash_pii_udf(value: str) -> str:
    """Hash PII with salt (deterministic)."""
    if value is None:
        return None
    combined = f"{value}{pii_salt}"
    return hashlib.sha256(combined.encode()).hexdigest()


# Register UDF
hash_pii = F.udf(hash_pii_udf, StringType())


# ==================== Load Bronze Data ====================

bronze_path = f"s3://{args['bronze_bucket']}/transactions/"
print(f"[Silver Job] Reading Bronze data from: {bronze_path}")

# Read last 7 days for historical aggregates
df_bronze = spark.read.parquet(bronze_path)

# Cast timestamp
df_bronze = df_bronze.withColumn('timestamp', F.col('timestamp').cast(TimestampType()))

print(f"[Silver Job] Loaded {df_bronze.count()} records from Bronze")


# ==================== Basic Transformations ====================

df = df_bronze.select(
    'transaction_id',
    'timestamp',
    'amount',
    F.col('user_id').alias('user_id_raw'),
    F.col('merchant_id').alias('merchant_id_raw'),
    'merchant_category',
    'transaction_type',
    'country',
    'currency',
    'is_fraud',
    'event_id',
    'schema_version'
)

# Tokenize PII
df = df.withColumn('user_id', hash_pii(F.col('user_id_raw')))
df = df.withColumn('merchant_id', hash_pii(F.col('merchant_id_raw')))

# Drop raw PII columns
df = df.drop('user_id_raw', 'merchant_id_raw')

print("[Silver Job] PII tokenization complete")


# ==================== Velocity Features ====================

def add_velocity_features(df, window_minutes: int, suffix: str):
    """Add velocity features for a time window."""
    window_spec = (
        Window
        .partitionBy('user_id')
        .orderBy(F.col('timestamp').cast('long'))
        .rangeBetween(-window_minutes * 60, 0)
    )
    
    df = df.withColumn(
        f'user_txn_count_{suffix}',
        F.count('transaction_id').over(window_spec) - 1  # Exclude current
    )
    
    df = df.withColumn(
        f'user_total_amount_{suffix}',
        F.sum('amount').over(window_spec) - F.col('amount')  # Exclude current
    )
    
    df = df.withColumn(
        f'user_avg_amount_{suffix}',
        F.when(
            F.col(f'user_txn_count_{suffix}') > 0,
            F.col(f'user_total_amount_{suffix}') / F.col(f'user_txn_count_{suffix}')
        ).otherwise(0.0)
    )
    
    return df


# Add velocity windows
print("[Silver Job] Computing velocity features...")
df = add_velocity_features(df, 5, '5m')    # 5 minutes
df = add_velocity_features(df, 60, '1h')   # 1 hour
df = add_velocity_features(df, 1440, '24h')  # 24 hours

print("[Silver Job] Velocity features complete")


# ==================== User Aggregates ====================

# User lifetime stats (up to current transaction)
user_window = (
    Window
    .partitionBy('user_id')
    .orderBy(F.col('timestamp').cast('long'))
    .rowsBetween(Window.unboundedPreceding, -1)
)

df = df.withColumn('user_lifetime_txn_count', F.count('transaction_id').over(user_window))
df = df.withColumn('user_lifetime_total_amount', F.sum('amount').over(user_window))
df = df.withColumn(
    'user_lifetime_avg_amount',
    F.when(
        F.col('user_lifetime_txn_count') > 0,
        F.col('user_lifetime_total_amount') / F.col('user_lifetime_txn_count')
    ).otherwise(0.0)
)

print("[Silver Job] User aggregates complete")


# ==================== Merchant Aggregates ====================

merchant_window = (
    Window
    .partitionBy('merchant_id')
    .orderBy(F.col('timestamp').cast('long'))
    .rowsBetween(Window.unboundedPreceding, -1)
)

df = df.withColumn('merchant_txn_count', F.count('transaction_id').over(merchant_window))
df = df.withColumn('merchant_total_amount', F.sum('amount').over(merchant_window))
df = df.withColumn('merchant_fraud_count', F.sum('is_fraud').over(merchant_window))
df = df.withColumn(
    'merchant_fraud_rate',
    F.when(
        F.col('merchant_txn_count') > 0,
        F.col('merchant_fraud_count') / F.col('merchant_txn_count')
    ).otherwise(0.0)
)

print("[Silver Job] Merchant aggregates complete")


# ==================== Derived Features ====================

# Amount deviation from user average
df = df.withColumn(
    'amount_vs_user_avg_ratio',
    F.when(
        F.col('user_lifetime_avg_amount') > 0,
        F.col('amount') / F.col('user_lifetime_avg_amount')
    ).otherwise(1.0)
)

# Hour of day (fraud patterns often temporal)
df = df.withColumn('hour_of_day', F.hour('timestamp'))

# Day of week
df = df.withColumn('day_of_week', F.dayofweek('timestamp'))

# Is weekend
df = df.withColumn('is_weekend', F.when(F.col('day_of_week').isin([1, 7]), 1).otherwise(0))

print("[Silver Job] Derived features complete")


# ==================== Write to Silver ====================

silver_path = f"s3://{args['silver_bucket']}/transactions/"

# Only write recent data (last 24 hours) to Silver
# Older data is for historical context only
cutoff_time = datetime.now() - timedelta(hours=24)
df_recent = df.filter(F.col('timestamp') >= F.lit(cutoff_time))

print(f"[Silver Job] Writing {df_recent.count()} records to Silver")

df_recent.write.mode('append').parquet(
    silver_path,
    partitionBy=['year', 'month', 'day'],
    compression='snappy'
)

print(f"[Silver Job] Silver data written to: {silver_path}")

# Commit job
job.commit()
print("[Silver Job] Complete")
